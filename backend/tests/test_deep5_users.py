"""深度五期测试：多用户数据隔离（JWT）+ media_url + 转写片断接口。"""
import io
import json

from PIL import Image

from app.core.database import SessionLocal
from app.llm.client import VisionResult, client as llm_client
from app.models import Asset


def _png(name: str, seed: int | None = None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), color=(seed or sum(ord(c) for c in name) % 200, 90, 150)).save(buf, "PNG")
    buf.seek(0)
    return buf.read()


def _upload(client, name: str, token: str | None = None, content: bytes | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/upload",
        files={"files": (name, content or _png(name), "image/png")},
        headers=headers,
    )


def _register(client, username: str = "alice") -> str:
    r = client.post("/api/auth/register", json={"username": username, "password": "pass1234"})
    assert r.status_code == 200
    return r.json()["access_token"]


def _seed_local_image(client, monkeypatch, name="城市夜景.png"):
    monkeypatch.setattr(
        llm_client,
        "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="城市夜景", tags=["夜景"], ocr=""),
    )
    return _upload(client, name)


def test_per_user_asset_isolation(client, monkeypatch):
    local = _seed_local_image(client, monkeypatch)
    local_id = local.json()["items"][0]["asset"]["id"]
    assert local.json()["items"][0]["asset"]["media_url"].startswith("/media/")

    token = _register(client)
    alice = client.post(
        "/api/upload",
        files={"files": ("营销方案.txt", "营销方案是关于增长与留存的分析文档".encode("utf-8"), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    alice_id = alice.json()["items"][0]["asset"]["id"]
    assert alice_id != local_id

    # 各自只看到自己的素材
    guest_list = client.get("/api/assets").json()
    assert all(a["id"] == local_id for a in guest_list["items"])
    alice_list = client.get("/api/assets", headers={"Authorization": f"Bearer {token}"}).json()
    assert all(a["id"] == alice_id for a in alice_list["items"])

    # 跨用户不可见（详情 / 检索 / 画像）
    assert client.get(f"/api/assets/{alice_id}").status_code == 404
    assert client.get(f"/api/assets/{local_id}", headers={"Authorization": f"Bearer {token}"}).status_code == 404

    hits = client.get("/api/search", params={"q": "夜景"}, headers={"Authorization": f"Bearer {token}"})
    assert all(h["asset"]["id"] != local_id for h in hits.json()["hits"])

    alice_profile = client.get("/api/domain/profile", headers={"Authorization": f"Bearer {token}"}).json()
    assert alice_profile["total"] == 1
    guest_profile = client.get("/api/domain/profile").json()
    assert guest_profile["total"] == 1
    assert alice_profile["top_tags"] != guest_profile["top_tags"] or alice_profile["summary"] != guest_profile["summary"]

    # 跨用户同内容不算重复（各自拥有一份）
    dup = _upload(client, "城市夜景.png", token, content=_png("城市夜景.png"))
    assert dup.json()["items"][0]["duplicate_of"] is None


def test_chat_sessions_isolated_per_user(client, monkeypatch):
    _seed_local_image(client, monkeypatch)
    token = _register(client)

    local_resp = client.post("/api/chat", json={"message": "帮我搜夜景", "session_id": "local-s"})
    assert local_resp.status_code == 200
    alice_resp = client.post(
        "/api/chat",
        json={"message": "帮我搜夜景", "session_id": "alice-s"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert alice_resp.status_code == 200

    guest_sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert any(s["id"] == "local-s" for s in guest_sessions)
    assert not any(s["id"] == "alice-s" for s in guest_sessions)

    alice_sessions = client.get("/api/chat/sessions", headers={"Authorization": f"Bearer {token}"}).json()["sessions"]
    assert any(s["id"] == "alice-s" for s in alice_sessions)
    assert not any(s["id"] == "local-s" for s in alice_sessions)

    # 跨用户读历史被拒
    assert client.get("/api/chat/sessions/alice-s/messages").status_code == 404
    assert (
        client.get(
            "/api/chat/sessions/local-s/messages",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 404
    )


def test_asset_segments_endpoint(client):
    with SessionLocal() as db:
        db.add(Asset(
            owner="local",
            name="会议录音",
            original_filename="m.mp3",
            modality="audio",
            mime_type="audio/mpeg",
            size_bytes=1,
            storage_path="uploads/audio/m.mp3",
            sha256="seg1",
            status="ready",
            duration=95.0,
            transcript_segments=json.dumps(
                [{"start": 10.0, "end": 40.0, "text": "增长与留存是重点"}], ensure_ascii=False
            ),
        ))
        db.commit()
        aid = db.query(Asset).filter(Asset.sha256 == "seg1").first().id

    r = client.get(f"/api/assets/{aid}/segments")
    assert r.status_code == 200
    body = r.json()
    assert body["duration"] == 95.0
    assert body["segments"][0]["start"] == 10.0
    assert "增长" in body["segments"][0]["text"]
