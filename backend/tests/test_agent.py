"""阶段 5 测试：Agent 工具层 + LangGraph 图 + SSE 接口（LLM 全 mock/兜底）。"""
import io

from PIL import Image

from app.agent.graph import agent_app
from app.agent.tools import domain_profile as tool_domain_profile
from app.agent.tools import search_assets as tool_search_assets
from app.llm.client import VisionResult, client as llm_client


def upload_image(client, name):
    buf = io.BytesIO()
    seed = sum(ord(ch) for ch in name)
    Image.new("RGB", (64, 48), color=(30 + seed % 180, 80, 160)).save(buf, format="PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def seed_night_scene(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime: VisionResult(description="城市夜景", tags=["夜景", "城市"], ocr=""),
    )
    upload_image(client, "城市夜景.png")


# ---------- 工具层 ----------

def test_tool_search_assets(client, monkeypatch):
    seed_night_scene(client, monkeypatch)
    result = tool_search_assets("夜景")
    assert result["ok"] is True
    assert result["assets"][0]["name"] == "城市夜景"


def test_tool_domain_profile(client):
    client.post("/api/upload", files={"files": ("plan.txt", "营销内容".encode(), "text/plain")})
    result = tool_domain_profile()
    assert result["ok"] is True
    assert "共" in result["summary"]


def test_tool_get_asset_detail_missing():
    from app.agent.tools import get_asset_detail

    result = get_asset_detail(999)
    assert result["ok"] is False


# ---------- LangGraph 图（无 Key 兜底路径） ----------

def test_agent_search_fallback(client, monkeypatch):
    seed_night_scene(client, monkeypatch)
    result = agent_app.invoke({
        "messages": [{"role": "user", "content": "帮我搜夜景"}],
        "intent": "", "params": {}, "tool_result": {}, "answer": "",
    })
    assert result["intent"] == "search"
    assert "城市夜景" in result["answer"]


def test_agent_profile_fallback(client):
    client.post("/api/upload", files={"files": ("plan.txt", "营销内容".encode(), "text/plain")})
    result = agent_app.invoke({
        "messages": [{"role": "user", "content": "我的素材库是什么领域"}],
        "intent": "", "params": {}, "tool_result": {}, "answer": "",
    })
    assert result["intent"] == "profile"
    assert "共" in result["answer"]


def test_agent_llm_intent_and_answer(client, monkeypatch):
    """mock LLM：意图识别 + 组织回答都走真实链路。"""
    seed_night_scene(client, monkeypatch)

    def fake_chat(messages, temperature=0.3, max_tokens=800):
        system = messages[0]["content"]
        if "意图识别" in system:
            return '{"intent": "search", "query": "夜景"}'
        return "为你找到素材 #1 城市夜景。相关描述：城市夜景。"

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    result = agent_app.invoke({
        "messages": [{"role": "user", "content": "帮我搜夜景"}],
        "intent": "", "params": {}, "tool_result": {}, "answer": "",
    })
    assert result["intent"] == "search"
    assert result["answer"].startswith("为你找到素材")


# ---------- SSE 接口 ----------

def test_chat_api_sse_fallback(client, monkeypatch):
    seed_night_scene(client, monkeypatch)
    resp = client.post("/api/chat", json={"message": "帮我搜夜景", "session_id": "sse-1"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "event: meta" in body
    assert "event: step" in body
    assert "event: answer" in body
    assert "城市夜景" in body


def test_chat_api_empty_message(client):
    resp = client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 200
    assert "消息不能为空" in resp.text
