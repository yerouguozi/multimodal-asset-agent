"""阶段 3 测试：混合检索（BM25+向量+重排）与领域画像。"""
import io

from PIL import Image

from app.llm.client import DomainInsight, SummaryResult, VisionResult, client as llm_client


def upload_image(client, name):
    buf = io.BytesIO()
    seed = sum(ord(ch) for ch in name)
    Image.new("RGB", (64, 48), color=(30 + seed % 180, 80 + seed % 90, 160)).save(buf, format="PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def test_hybrid_search_bm25_ranking(client, monkeypatch):
    """纯 BM25（无向量/重排）下，相关素材排第一。"""
    monkeypatch.setattr(llm_client, "embed_texts", lambda texts: None)
    monkeypatch.setattr(llm_client, "rerank", lambda q, docs: None)

    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime: VisionResult(description="夜晚城市建筑剪影", tags=["夜景", "建筑"], ocr=""),
    )
    upload_image(client, "a.png")
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime: VisionResult(description="产品海报促销活动", tags=["营销", "海报"], ocr=""),
    )
    upload_image(client, "b.png")

    r = client.get("/api/search", params={"q": "夜景"})
    hits = r.json()["hits"]
    assert hits[0]["asset"]["name"] == "a"

    r = client.get("/api/search", params={"q": "促销"})
    assert r.json()["hits"][0]["asset"]["name"] == "b"


def test_search_rerank_applied(client, monkeypatch):
    """有重排模型时，按重排分数排序。"""
    monkeypatch.setattr(llm_client, "embed_texts", lambda texts: None)
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime: VisionResult(description="夜景图片", tags=["夜景"], ocr=""),
    )
    upload_image(client, "a.png")
    upload_image(client, "b.png")

    # 重排故意把 b 排在前面
    monkeypatch.setattr(llm_client, "rerank", lambda q, docs: [0.2, 0.9])
    r = client.get("/api/search", params={"q": "夜景"})
    hits = r.json()["hits"]
    assert len(hits) == 2
    assert hits[0]["asset"]["name"] == "b"
    assert abs(hits[0]["score"] - 0.9) < 1e-6


def test_domain_profile_with_llm(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime: VisionResult(description="城市夜景", tags=["夜景", "城市"], ocr=""),
    )
    upload_image(client, "n1.png")
    upload_image(client, "n2.png")
    monkeypatch.setattr(
        llm_client, "summarize_text",
        lambda text: SummaryResult(summary="营销方案", tags=["营销"]),
    )
    client.post("/api/upload", files={"files": ("plan.txt", "营销内容".encode(), "text/plain")})

    monkeypatch.setattr(
        llm_client, "domain_insight",
        lambda ms, tags: DomainInsight(labels=["城市影像素材库"], summary="以城市夜景图片为主"),
    )
    d = client.get("/api/domain/profile").json()
    assert d["by_modality"] == {"image": 2, "document": 1}
    assert d["labels"] == ["城市影像素材库"]
    assert d["summary"] == "以城市夜景图片为主"
    assert d["adaptive_weights"]["transcript"] == 1.0  # 无视频/音频不提升
    assert any(t["name"] == "夜景" for t in d["top_tags"])


def test_domain_profile_fallback(client):
    """无 LLM Key：确定性兜底总结。"""
    client.post("/api/upload", files={"files": ("plan.txt", "营销内容".encode(), "text/plain")})
    d = client.get("/api/domain/profile").json()
    assert d["labels"] == []
    assert "共" in d["summary"]
    assert d["by_modality"] == {"document": 1}
