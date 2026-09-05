"""深度八期测试：模型成本日志按 owner 隔离。"""
import io

from PIL import Image

from app.core.database import SessionLocal
from app.llm.client import SummaryResult, VisionResult, client as llm_client
from app.models import UsageLog
from app.usage import record_usage


def _upload_png(client, name):
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), color=(sum(ord(c) for c in name) % 200, 90, 150)).save(buf, "PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def test_usage_logs_isolated_per_owner(client, monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="城市夜景", tags=["夜景"], ocr=""),
    )
    monkeypatch.setattr(
        llm_client,
        "summarize_text",
        lambda text: SummaryResult(summary="文档摘要", tags=["文档"]),
    )
    _upload_png(client, "访客图片.png")

    token = client.post(
        "/api/auth/register", json={"username": "carol", "password": "pass1234"}
    ).json()["access_token"]
    client.post(
        "/api/upload",
        files={"files": ("用户文档.txt", "这是卡罗尔的私有文档内容".encode("utf-8"), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    guest = client.get("/api/usage/summary").json()
    carol = client.get("/api/usage/summary", headers={"Authorization": f"Bearer {token}"}).json()
    assert guest["total_calls"] > 0
    assert carol["total_calls"] > 0
    with SessionLocal() as db:
        owners = {r.owner for r in db.query(UsageLog).all()}
        local_count = db.query(UsageLog).filter(UsageLog.owner == "local").count()
        carol_count = db.query(UsageLog).filter(UsageLog.owner == "carol").count()
    assert "local" in owners and "carol" in owners
    assert guest["total_calls"] == local_count
    assert carol["total_calls"] == carol_count


def test_record_usage_explicit_owner_without_asset():
    record_usage(None, "Qwen/Qwen-Image", "image_gen", owner="carol")
    with SessionLocal() as db:
        row = db.query(UsageLog).filter(UsageLog.owner == "carol").first()
        assert row is not None and row.asset_id is None
        assert row.operation == "image_gen"
