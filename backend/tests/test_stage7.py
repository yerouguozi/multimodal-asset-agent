"""阶段 7 测试：模型路由 / 文生图 / 素材处理 / 成本追踪。"""
import io

from PIL import Image

from app.agent.graph import _clean_prompt, _parse_transform
from app.agent.tools import generate_image, transform_asset
from app.core.config import settings
from app.llm.client import VisionResult, client as llm_client
from app.models import Asset
from app.pipeline.processors import process_image


def make_png(size):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(40, 90, 160)).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def upload_png(client, name, size=(64, 48)):
    return client.post("/api/upload", files={"files": (name, make_png(size), "image/png")})


# ---------- 模型路由 ----------

def _spy_vision(monkeypatch, calls):
    def spy(b64, mime, model=None):
        calls["model"] = model
        return VisionResult(description="测试图", tags=["测试"], ocr="")

    monkeypatch.setattr(llm_client, "vision_describe", spy)


def _write_asset(tmp_path, name, size):
    p = tmp_path / "uploads" / "image" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(make_png(size))
    return Asset(
        id=1, name=name, original_filename=name, modality="image", mime_type="image/png",
        size_bytes=1, storage_path=f"uploads/image/{name}", sha256=name, status="pending",
    )


def test_model_routing_small_image(monkeypatch, tmp_path):
    calls: dict = {}
    _spy_vision(monkeypatch, calls)
    asset = _write_asset(tmp_path, "s.png", (64, 48))
    process_image(asset, llm_client, tmp_path)
    assert calls["model"] == settings.vision_model_cheap


def test_model_routing_large_image(monkeypatch, tmp_path):
    calls: dict = {}
    _spy_vision(monkeypatch, calls)
    asset = _write_asset(tmp_path, "l.png", (1200, 800))
    process_image(asset, llm_client, tmp_path)
    assert calls["model"] == settings.vision_model


# ---------- 指令解析 ----------

def test_clean_prompt():
    assert _clean_prompt("帮我生成一张城市夜景插画") == "城市夜景插画"


def test_parse_transform():
    assert _parse_transform("把 #3 压缩一下") == (3, "compress", {})
    assert _parse_transform("把 #2 转成 mp4") == (2, "convert", {"format": "mp4"})


# ---------- 文生图工具 ----------

def test_generate_image_tool_ingests(client, monkeypatch):
    monkeypatch.setattr(llm_client, "generate_image", lambda prompt: make_png((256, 256)))
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="生成的城市夜景插画", tags=["生成", "夜景"], ocr=""),
    )
    result = generate_image("城市夜景插画")
    assert result["ok"] is True
    assert result["assets"][0]["description"] == "生成的城市夜景插画"

    s = client.get("/api/usage/summary").json()
    assert s["total_calls"] >= 1
    assert settings.image_gen_model in s["by_model"]


def test_generate_image_client(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "siliconflow_api_key", "test-key")
    import app.llm.client as llm_module

    class FakeGenResp:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"url": "http://x/a.png"}]}

    class FakeImgResp:
        status_code = 200
        content = b"PNGDATA"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(llm_module.httpx, "post", lambda *a, **k: FakeGenResp())
    monkeypatch.setattr(llm_module.httpx, "get", lambda *a, **k: FakeImgResp())
    assert llm_client.generate_image("测试") == b"PNGDATA"


# ---------- 素材处理 ----------

def test_transform_asset_image_resize(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="原图描述", tags=["原"], ocr=""),
    )
    r = upload_png(client, "原图.png", (400, 300))
    aid = r.json()["items"][0]["asset"]["id"]

    result = transform_asset(aid, "resize", {"max_side": 100})
    assert result["ok"] is True
    new_id = result["assets"][0]["id"]
    detail = client.get(f"/api/assets/{new_id}").json()
    assert detail["status"] == "ready"
    assert detail["description"] == "原图描述"
    assert detail["width"] is not None and detail["width"] <= 100
    # 原素材仍在
    assert client.get(f"/api/assets/{aid}").status_code == 200


def test_transform_asset_missing():
    result = transform_asset(999, "compress", {})
    assert result["ok"] is False


def test_transform_asset_unsupported_operation(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="x", tags=[], ocr=""),
    )
    r = upload_png(client, "a.png")
    aid = r.json()["items"][0]["asset"]["id"]
    result = transform_asset(aid, "crop", {})
    assert result["ok"] is False


# ---------- 成本追踪 ----------

def test_usage_summary_api(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="图", tags=["图"], ocr=""),
    )
    upload_png(client, "a.png")
    s = client.get("/api/usage/summary").json()
    assert s["total_calls"] >= 1
    assert s["by_model"]
    assert s["total_cost"] >= 0
