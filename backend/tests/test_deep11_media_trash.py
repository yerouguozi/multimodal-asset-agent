"""深度十一期：媒体访问鉴权 + 回收站/恢复/彻底删除 + 失败重试。"""
import io

from PIL import Image

from app.core.database import SessionLocal
from app.llm.client import VisionResult, client as llm_client
from app.models import Asset


def _upload_png(client, name):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color=(sum(ord(c) for c in name) % 200, 90, 150)).save(buf, "PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def _seed(client, monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="图", tags=["图"], ocr=""),
    )
    return _upload_png(client, "访客图.png")


def test_media_access_requires_owner(client, monkeypatch):
    local = _seed(client, monkeypatch)
    media = local.json()["items"][0]["asset"]["media_url"]
    # 访客自己的素材可直接访问
    assert client.get(media).status_code == 200

    token = client.post(
        "/api/auth/register", json={"username": "mediauser", "password": "pass1234"}
    ).json()["access_token"]
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color=(90, 90, 150)).save(buf, "PNG")
    bob = client.post(
        "/api/upload",
        files={"files": ("用户图.png", buf.getvalue(), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    bob_media = bob.json()["items"][0]["asset"]["media_url"]
    # 未登录访客访问 bob 素材 -> 404
    assert client.get(bob_media).status_code == 404
    # bob 用 ?token= 访问自己素材 -> 200；访问访客素材 -> 404
    assert client.get(f"{bob_media}?token={token}").status_code == 200
    assert client.get(f"{media}?token={token}").status_code == 404


def test_trash_restore_purge(client, monkeypatch):
    up = _seed(client, monkeypatch)
    aid = up.json()["items"][0]["asset"]["id"]
    assert client.delete(f"/api/assets/{aid}").json()["trashed"] is True
    assert client.get("/api/assets").json()["total"] == 0
    assert client.get("/api/assets/trash").json()["total"] == 1
    assert client.get(f"/api/assets/{aid}").status_code == 404

    restore = client.post(f"/api/assets/trash/{aid}/restore")
    assert restore.status_code == 200
    assert client.get("/api/assets").json()["total"] == 1

    client.delete(f"/api/assets/{aid}")
    assert client.delete(f"/api/assets/trash/{aid}").json()["ok"] is True
    with SessionLocal() as db:
        assert db.get(Asset, aid) is None


def test_retry_failed_asset(client, monkeypatch):
    up = _seed(client, monkeypatch)
    aid = up.json()["items"][0]["asset"]["id"]
    assert client.post(f"/api/assets/{aid}/retry").status_code == 400  # 非失败不可重试
    with SessionLocal() as db:
        a = db.get(Asset, aid)
        a.status = "failed"
        a.error_message = "人工置为失败"
        db.commit()
    r = client.post(f"/api/assets/{aid}/retry")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
