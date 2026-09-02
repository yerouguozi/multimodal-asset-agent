"""深度二期测试：多模态向量空间 / 三路融合检索 / 图片 VL 嵌入。"""
import io

from PIL import Image

from app.core.config import settings
from app.llm.client import VisionResult, client as llm_client
from app.retrieval.vector_store import vector_store


def upload_png(client, name):
    buf = io.BytesIO()
    seed = sum(ord(c) for c in name)
    Image.new("RGB", (64, 48), color=(30 + seed % 180, 80, 160)).save(buf, format="PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def test_vector_store_per_model_spaces(tmp_path):
    """不同模型向量维度不同，按模型分空间存储且模型名可还原。"""
    from app.retrieval.vector_store import LocalVectorStore

    path = tmp_path / "v.npz"
    vs = LocalVectorStore(path)
    vs.add(1, [0.1] * 1024, "BAAI/bge-m3")
    vs.add(1, [0.2] * 4096, "Qwen/Qwen3-VL-Embedding-8B")
    vs.add(2, [0.9] * 4096, "Qwen/Qwen3-VL-Embedding-8B")
    assert len(vs) == 3

    hits = vs.search([0.2] * 4096, "Qwen/Qwen3-VL-Embedding-8B", top_k=2)
    assert abs(hits[1] - 1.0) < 1e-6

    vs.delete(1)
    assert len(vs) == 1

    # 持久化往返：模型名保真
    vs2 = LocalVectorStore(path)
    assert "Qwen/Qwen3-VL-Embedding-8B" in vs2.models()
    assert abs(vs2.search([0.9] * 4096, "Qwen/Qwen3-VL-Embedding-8B", top_k=1)[2] - 1.0) < 1e-6


def test_search_strategy_tri_uses_vl(client, monkeypatch):
    """三路融合策略（tri）启用图片 VL 向量；纯文本策略（rrf）不用。"""
    r = upload_png(client, "夜景图.png")
    aid = r.json()["items"][0]["asset"]["id"]
    vec = [0.5] * 4096
    vector_store.add(aid, vec, settings.vl_embedding_model)

    monkeypatch.setattr(llm_client, "embed_texts", lambda texts: None)
    monkeypatch.setattr(llm_client, "embed_texts_vl", lambda texts: [vec])
    monkeypatch.setattr(llm_client, "rerank", lambda q, docs: None)

    from app.core.database import SessionLocal
    from app.retrieval import search as search_service

    with SessionLocal() as db:
        hits_tri = search_service.search(db, "深蓝剪影", strategy="tri")
        assert len(hits_tri) == 1
        hits_rrf = search_service.search(db, "深蓝剪影", strategy="rrf")
        assert hits_rrf == []


def test_pipeline_image_vl_embed(client, monkeypatch):
    """图片入库后自动生成 VL 图片向量（多模态向量空间）。"""
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="测试图", tags=["图"], ocr=""),
    )
    monkeypatch.setattr(llm_client, "embed_image", lambda b64, mime="image/jpeg": [0.3] * 4096)

    r = upload_png(client, "p.png")
    assert r.json()["items"][0]["asset"]["status"] == "ready"
    assert settings.vl_embedding_model in vector_store.models()
