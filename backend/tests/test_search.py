"""关键词检索测试（无 API Key 时走确定性兜底）。"""
import io

from PIL import Image


def upload_image(client, name, size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(120, 40, 90)).save(buf, format="PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def test_search_by_filename(client):
    upload_image(client, "城市夜景.png")
    upload_image(client, "产品海报.png")
    r = client.get("/api/search", params={"q": "夜景"})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert len(hits) >= 1
    assert hits[0]["asset"]["name"] == "城市夜景"


def test_search_no_result(client):
    upload_image(client, "城市夜景.png")
    r = client.get("/api/search", params={"q": "完全不存在的内容xyz"})
    assert r.json()["hits"] == []


def test_search_document_text(client):
    client.post(
        "/api/upload",
        files={"files": ("笔记.txt", "深度学习与多模态检索技术笔记".encode(), "text/plain")},
    )
    r = client.get("/api/search", params={"q": "多模态"})
    assert len(r.json()["hits"]) == 1


def test_search_filter_modality(client):
    upload_image(client, "夜景.png")
    client.post("/api/upload", files={"files": ("文档.txt", "夜景描述".encode(), "text/plain")})
    r = client.get("/api/search", params={"q": "夜景", "modality": "image"})
    assert all(h["asset"]["modality"] == "image" for h in r.json()["hits"])
