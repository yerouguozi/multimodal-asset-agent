"""深度十期测试：每用户模型调用配额（预检 + summary 快照）。"""
import io

from PIL import Image

from app.core.config import settings
from app.core.database import SessionLocal
from app.llm.client import VisionResult, client as llm_client
from app.models import UsageLog
from app.usage import ensure_quota, quota_usage


def _upload_png(client, name):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color=(sum(ord(c) for c in name) % 200, 90, 150)).save(buf, "PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def test_quota_summary_exposed(client):
    summary = client.get("/api/usage/summary").json()
    assert summary["quota"]["daily"]["limit"] == settings.usage_daily_limit
    assert summary["quota"]["daily"]["remaining"] == settings.usage_daily_limit


def test_ensure_quota_rejects_when_over_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "usage_daily_limit", 3)
    with SessionLocal() as db:
        for _ in range(3):
            db.add(UsageLog(owner="local", model="x", operation="test", cost_estimate=0))
        db.commit()
    with SessionLocal() as db:
        assert quota_usage(db, "local")["today"] == 3
    try:
        ensure_quota("local", 1)
        raise AssertionError("应抛 429")
    except Exception as e:
        assert getattr(e, "status_code", None) == 429


def test_upload_returns_429_when_quota_exceeded(client, monkeypatch):
    monkeypatch.setattr(llm_client, "vision_describe",
                        lambda b64, mime, model=None: VisionResult(description="图", tags=[], ocr=""))
    monkeypatch.setattr(settings, "usage_daily_limit", 3)
    with SessionLocal() as db:
        for _ in range(3):
            db.add(UsageLog(owner="local", model="x", operation="test", cost_estimate=0))
        db.commit()
    assert _upload_png(client, "超限.png").status_code == 429


def test_quota_usage_by_owner(client):
    with SessionLocal() as db:
        db.add(UsageLog(owner="local", model="a", operation="t", cost_estimate=0))
        db.add(UsageLog(owner="bob", model="a", operation="t", cost_estimate=0))
        db.commit()
    assert quota_usage(db, "local")["today"] == 1
    assert quota_usage(db, "bob")["today"] == 1
