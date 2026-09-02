"""上传接口测试（图片/文档/重复/不支持类型）。"""
import io

from PIL import Image


def make_png(size=(64, 48), color=(30, 80, 160)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def test_upload_image_ready(client):
    data = make_png()
    r = client.post("/api/upload", files={"files": ("night.png", data, "image/png")})
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["asset"]["status"] == "ready"
    assert item["asset"]["modality"] == "image"
    assert item["asset"]["thumbnail_url"]


def test_upload_duplicate(client):
    data = make_png()
    first = client.post("/api/upload", files={"files": ("a.png", data, "image/png")}).json()["items"][0]
    second = client.post("/api/upload", files={"files": ("b.png", data, "image/png")}).json()["items"][0]
    assert second["duplicate_of"] == first["asset"]["id"]
    assert client.get("/api/assets").json()["total"] == 1


def test_upload_unknown_type(client):
    r = client.post("/api/upload", files={"files": ("archive.xyz", b"123", "application/x-xyz")})
    assert r.status_code == 200
    assert "不支持" in r.json()["items"][0]["error"]


def test_upload_document_text_extracted(client):
    content = "本季度产品营销方案：目标用户是年轻群体，主打社交媒体推广。"
    r = client.post("/api/upload", files={"files": ("plan.txt", content.encode(), "text/plain")})
    assert r.status_code == 200
    aid = r.json()["items"][0]["asset"]["id"]
    detail = client.get(f"/api/assets/{aid}").json()
    assert detail["status"] == "ready"
    assert "营销" in detail["text_content"]
