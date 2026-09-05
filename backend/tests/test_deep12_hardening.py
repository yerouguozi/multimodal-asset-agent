"""高优先级加固的回归测试：jobs 鉴权 / 上传限流 / 重启恢复 / 检索缓存失效 / 分批嵌入。"""
import io

from PIL import Image

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Asset
from app.pipeline.manager import manager


def _png(name="t.png"):
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), color=(10, 10, 10)).save(buf, format="PNG")
    buf.seek(0)
    return name, buf.read(), "image/png"


def test_jobs_endpoint_is_owner_isolated(client):
    r = client.post("/api/auth/register", json={"username": "jobsowner", "password": "pass1234"})
    token = r.json()["access_token"]
    up = client.post("/api/upload", headers={"Authorization": f"Bearer {token}"}, files={"files": _png()})
    asset_id = up.json()["items"][0]["asset"]["id"]

    # 访客（local）查别人的任务 → 404；本人查 → 200
    assert client.get(f"/api/jobs/{asset_id}").status_code == 404
    ok = client.get(f"/api/jobs/{asset_id}", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["asset_id"] == asset_id


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = client.post("/api/upload", files={"files": ("big.png", b"x" * 10, "image/png")})
    item = r.json()["items"][0]
    assert "上限" in (item.get("error") or "")


def test_upload_still_round_trips(client):
    """流式落盘后常规上传路径不变：入库 + 同步处理就绪。"""
    r = client.post("/api/upload", files={"files": _png("夜色.png")})
    item = r.json()["items"][0]
    assert item["asset"]["status"] == "ready"

    dup = client.post("/api/upload", files={"files": _png("夜色副本.png")})
    assert dup.json()["items"][0].get("duplicate_of") == item["asset"]["id"]


def test_recover_interrupted_sync_marks_failed():
    with SessionLocal() as db:
        a = Asset(
            owner="local", name="中断", original_filename="x.png", modality="image",
            storage_path="uploads/image/x.png", sha256="recover-sync-1", status="processing",
        )
        db.add(a)
        db.commit()
        aid = a.id
    assert manager.recover_interrupted() == 1
    with SessionLocal() as db:
        a = db.get(Asset, aid)
        assert a.status == "failed"
        assert "重试" in (a.error_message or "")


def test_recover_interrupted_async_requeues(monkeypatch):
    monkeypatch.setattr(settings, "ingestion_mode", "async")
    with SessionLocal() as db:
        a = Asset(
            owner="local", name="恢复", original_filename="y.png", modality="image",
            storage_path="uploads/image/y.png", sha256="recover-async-1", status="processing",
        )
        db.add(a)
        db.commit()
        aid = a.id
    while not manager._queue.empty():  # 清掉可能的残留
        manager._queue.get_nowait()
    assert manager.recover_interrupted() == 1
    assert manager._queue.get_nowait() == aid
    with SessionLocal() as db:
        assert db.get(Asset, aid).status == "pending"


def test_search_cache_invalidates_on_description_change(client):
    """检索分词缓存的指纹失效：改描述后新词立刻可被搜到。"""
    up = client.post("/api/upload", files={"files": _png("旧名字.png")})
    aid = up.json()["items"][0]["asset"]["id"]
    assert client.get("/api/search", params={"q": "蓝莓芝士蛋糕"}).json()["hits"] == []
    client.patch(f"/api/assets/{aid}", json={"description": "蓝莓芝士蛋糕的特写镜头"})
    r = client.get("/api/search", params={"q": "蓝莓芝士蛋糕"})
    assert len(r.json()["hits"]) == 1


def test_embed_texts_batched_splits(monkeypatch):
    from app.llm.client import client as llm_client

    calls = []

    def fake_embed(texts):
        calls.append(len(texts))
        return [[0.0] for _ in texts]

    monkeypatch.setattr(llm_client, "embed_texts", fake_embed)
    vecs = llm_client.embed_texts_batched([f"t{i}" for i in range(70)])
    assert len(vecs) == 70
    assert calls == [64, 6]


def test_embed_texts_batched_fails_closed(monkeypatch):
    from app.llm.client import client as llm_client

    monkeypatch.setattr(llm_client, "embed_texts", lambda texts: None)
    assert llm_client.embed_texts_batched(["a", "b"]) is None
