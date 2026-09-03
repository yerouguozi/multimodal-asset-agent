"""深度九期测试：批量 ZIP 打包下载（仅限本人素材）。"""
import io

from PIL import Image

from app.llm.client import VisionResult, client as llm_client


def _upload_png(client, name):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color=(sum(ord(c) for c in name) % 200, 90, 150)).save(buf, "PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def _seed(client, monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="测试图", tags=["测试"], ocr=""),
    )
    return _upload_png(client, "批量图一.png"), _upload_png(client, "批量图二.png")


def test_batch_download_zip(client, monkeypatch):
    a, b = _seed(client, monkeypatch)
    ids = [a.json()["items"][0]["asset"]["id"], b.json()["items"][0]["asset"]["id"]]
    r = client.post("/api/assets/download-zip", json={"ids": ids})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.content[:2] == b"PK"
    assert client.post("/api/assets/download-zip", json={"ids": []}).status_code == 400


def test_batch_download_scoped_to_owner(client, monkeypatch):
    local, _ = _seed(client, monkeypatch)
    local_id = local.json()["items"][0]["asset"]["id"]
    token = client.post(
        "/api/auth/register", json={"username": "zipuser", "password": "pass1234"}
    ).json()["access_token"]
    r = client.post(
        "/api/assets/download-zip",
        json={"ids": [local_id]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
