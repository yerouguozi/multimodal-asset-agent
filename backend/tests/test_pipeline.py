"""入库流水线测试：mock 视觉模型，验证自动打标/描述/OCR 落地。"""
import io

from PIL import Image

from app.llm.client import VisionResult, client as llm_client


def test_image_pipeline_with_mocked_vision(client, monkeypatch):
    def fake_describe(image_b64, mime):
        return VisionResult(
            description="城市夜景，摩天大楼，有雾霾",
            tags=["夜景", "城市", "雾霾"],
            ocr="SIGN",
        )

    monkeypatch.setattr(llm_client, "vision_describe", fake_describe)

    buf = io.BytesIO()
    Image.new("RGB", (80, 60), color=(10, 10, 80)).save(buf, format="PNG")
    buf.seek(0)
    r = client.post("/api/upload", files={"files": ("photo.png", buf.read(), "image/png")})
    item = r.json()["items"][0]["asset"]

    assert item["description"] == "城市夜景，摩天大楼，有雾霾"
    assert {t["name"] for t in item["tags"]} == {"夜景", "城市", "雾霾"}
    assert item["ocr_text"] == "SIGN"

    # 打标后按描述/标签检索
    hits = client.get("/api/search", params={"q": "雾霾"}).json()["hits"]
    assert len(hits) == 1


def test_document_pipeline_with_mocked_summary(client, monkeypatch):
    from app.llm.client import SummaryResult

    def fake_summarize(text):
        return SummaryResult(summary="产品营销方案摘要", tags=["营销", "方案"])

    monkeypatch.setattr(llm_client, "summarize_text", fake_summarize)

    client.post("/api/upload", files={"files": ("plan.txt", "营销内容".encode(), "text/plain")})
    hits = client.get("/api/search", params={"q": "营销"}).json()["hits"]
    assert len(hits) == 1
    assert hits[0]["asset"]["description"] == "产品营销方案摘要"
