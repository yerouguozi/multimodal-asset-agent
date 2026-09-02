"""阶段 8 测试：JWT 认证 + 质控平台兼容会话接口。"""
import io

from PIL import Image

from app.llm.client import VisionResult, client as llm_client


def _register(client, username="evaluser", password="pass1234"):
    return client.post("/api/auth/register", json={"username": username, "password": password})


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def seed_asset(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="城市夜景", tags=["夜景"], ocr=""),
    )
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color=(30, 80, 160)).save(buf, format="PNG")
    buf.seek(0)
    client.post("/api/upload", files={"files": ("夜景.png", buf.read(), "image/png")})


# ---------- 认证 ----------

def test_register_and_login(client):
    r = _register(client)
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert token

    dup = _register(client)
    assert dup.status_code == 409

    bad = client.post("/api/auth/login", json={"username": "evaluser", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"username": "evaluser", "password": "pass1234"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]


def test_auth_required(client):
    assert client.post("/api/sessions", json={"title": "x"}).status_code == 401
    assert client.post("/api/sessions/abc/messages", json={"content": "hi"}).status_code == 401


# ---------- 质控平台兼容接口 ----------

def test_qc_session_flow(client, monkeypatch):
    """CustomerServiceDriver 协议：建会话 → 发消息 → 返回 [content, tool_calls]。"""
    seed_asset(client, monkeypatch)
    token = _register(client).json()["access_token"]
    headers = _auth_header(token)

    sess = client.post("/api/sessions", json={"title": "评测"}, headers=headers)
    assert sess.status_code == 200
    sid = sess.json()["id"]

    msg = client.post(f"/api/sessions/{sid}/messages", json={"content": "帮我搜夜景"}, headers=headers)
    assert msg.status_code == 200
    body = msg.json()
    assert isinstance(body, list) and body
    last = body[-1]
    assert "城市夜景" in last["content"]
    names = [t["name"] for t in last["tool_calls"]]
    assert "search_assets" in names


def test_qc_session_not_found(client):
    token = _register(client).json()["access_token"]
    r = client.post("/api/sessions/nope/messages", json={"content": "hi"}, headers=_auth_header(token))
    assert r.status_code == 404
