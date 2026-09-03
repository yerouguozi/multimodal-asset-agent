"""深度六期测试：检索日志/P95 指标 + Agent 回答引用校验（防幻觉）。"""
import io

from PIL import Image

from app.agent.graph import agent_app, verify_citations
from app.core.database import SessionLocal
from app.llm.client import VisionResult, client as llm_client
from app.models import SearchLog


def _upload_png(client, name):
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), color=(sum(ord(c) for c in name) % 200, 90, 150)).save(buf, "PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def _seed(client, monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="城市夜景", tags=["夜景"], ocr=""),
    )
    _upload_png(client, "城市夜景.png")


def test_search_log_and_metrics(client, monkeypatch):
    _seed(client, monkeypatch)
    r = client.get("/api/search", params={"q": "夜景"})
    assert r.status_code == 200
    with SessionLocal() as db:
        rows = db.query(SearchLog).all()
        assert len(rows) == 1
        assert rows[0].owner == "local"
        assert rows[0].source == "api"
        assert rows[0].hits_count >= 1
        assert rows[0].latency_ms >= 0

    m = client.get("/api/metrics/search").json()
    assert m["total_queries"] == 1
    assert m["avg_latency_ms"] >= 0
    assert m["p95_latency_ms"] >= 0
    assert m["avg_hits"] >= 1
    assert m["by_source"].get("api") == 1
    assert m["top_queries"][0]["query"] == "夜景"


def test_agent_tool_search_logged(client, monkeypatch):
    _seed(client, monkeypatch)
    from app.agent.tools import search_assets

    search_assets("夜景")
    with SessionLocal() as db:
        rows = db.query(SearchLog).all()
        assert len(rows) == 1
        assert rows[0].source == "agent-tool"


def test_metrics_isolated_per_owner(client, monkeypatch):
    _seed(client, monkeypatch)
    r = client.post("/api/auth/register", json={"username": "bob", "password": "pass1234"})
    token = r.json()["access_token"]
    client.get("/api/search", params={"q": "夜景"})
    client.get("/api/search", params={"q": "夜景"}, headers={"Authorization": f"Bearer {token}"})

    guest = client.get("/api/metrics/search").json()
    alice = client.get("/api/metrics/search", headers={"Authorization": f"Bearer {token}"}).json()
    assert guest["total_queries"] == 1
    assert alice["total_queries"] == 1


def test_verify_citations_marks_invalid_refs():
    results = [{"assets": [{"id": 1, "name": "城市夜景"}]}]
    assert "99" in verify_citations("推荐 #1 和 #99", results)
    assert verify_citations("推荐 #1", results) == "推荐 #1"


def test_agent_answer_citation_guard(client, monkeypatch):
    _seed(client, monkeypatch)

    def fake_chat(messages, temperature=0.3, max_tokens=800):
        system = messages[0]["content"]
        if "任务规划器" in system:
            return '{"steps": []}'
        return "这是回答，引用了 #99 但工具没有这个素材。"

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    result = agent_app.invoke({
        "messages": [{"role": "user", "content": "闲聊一下"}],
        "plan": [], "step_index": 0, "results": [],
        "tool_result": {}, "tool_used": None, "intent": "", "answer": "",
    })
    assert "引用校验" in result["answer"]
    assert "#99" in result["answer"]


def test_search_strategy_param_and_metrics_extended(client, monkeypatch):
    _seed(client, monkeypatch)
    assert client.get("/api/search", params={"q": "夜景", "strategy": "nope"}).status_code == 422
    client.get("/api/search", params={"q": "夜景", "strategy": "bm25"})
    client.get("/api/search", params={"q": "夜景", "strategy": "gate"})

    m = client.get("/api/metrics/search").json()
    assert m["total_queries"] == 2
    assert m["by_strategy"] == {"bm25": 1, "gate": 1}
    assert len(m["recent"]) == 2
    assert m["recent"][-1]["strategy"] == "gate"
    assert m["recent"][-1]["query"] == "夜景"
