"""深度四期测试：Agent 实时执行轨迹（结构化事件）+ 多会话历史接口。"""
import io

from PIL import Image

from app.api.chat import run_agent
from app.llm.client import VisionResult, client as llm_client


def _upload_png(client, name):
    buf = io.BytesIO()
    seed = sum(ord(c) for c in name)
    Image.new("RGB", (64, 48), color=(30 + seed % 180, 80, 160)).save(buf, "PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def _seed_night_scene(client, monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="城市夜景", tags=["夜景", "城市"], ocr=""),
    )
    _upload_png(client, "城市夜景.png")


def test_run_agent_emits_structured_events(client, monkeypatch):
    """run_agent 的 emit 回调应产出 plan 与 tool 结构化事件（含命中素材）。"""
    _seed_night_scene(client, monkeypatch)
    events: list[tuple[str, dict]] = []

    answer, steps, tools = run_agent("帮我搜夜景", "trace-1", lambda name, data: events.append((name, data)))

    assert answer and "城市夜景" in answer
    assert tools == ["search_assets"]
    assert steps and steps[0]["stage"] == "intent"
    names = [e[0] for e in events]
    assert "plan" in names and "tool" in names and "step" in names
    plan = dict(events)["plan"]
    assert plan["intent"] == "search"
    assert plan["steps"][0]["tool"] == "search_assets"
    tool = dict(events)["tool"]
    assert tool["ok"] is True
    assert tool["assets"] and tool["assets"][0]["name"] == "城市夜景"
    assert tool["elapsed_ms"] >= 0


def test_chat_api_sse_carries_plan_and_tool_events(client, monkeypatch):
    _seed_night_scene(client, monkeypatch)
    resp = client.post("/api/chat", json={"message": "帮我搜夜景", "session_id": "trace-sse"})
    assert resp.status_code == 200
    body = resp.text
    for event in ("event: meta", "event: plan", "event: tool", "event: step", "event: answer"):
        assert event in body
    assert '"tool": "search_assets"' in body
    assert '"assets"' in body


def test_session_list_and_history_endpoints(client, monkeypatch):
    _seed_night_scene(client, monkeypatch)
    run_agent("帮我搜夜景", "hist-1")
    run_agent("再帮我看看 #1", "hist-1")

    sessions = client.get("/api/chat/sessions")
    assert sessions.status_code == 200
    items = sessions.json()["sessions"]
    assert any(s["id"] == "hist-1" for s in items)
    hist = next(s for s in items if s["id"] == "hist-1")
    assert hist["title"]  # 首条用户消息自动作为标题
    assert hist["message_count"] == 4
    assert hist["last_message"]

    msgs = client.get("/api/chat/sessions/hist-1/messages")
    assert msgs.status_code == 200
    rows = msgs.json()["messages"]
    assert len(rows) == 4
    assert rows[0]["role"] == "user"
    assert rows[-1]["role"] == "assistant"

    missing = client.get("/api/chat/sessions/no-such/messages")
    assert missing.status_code == 404
