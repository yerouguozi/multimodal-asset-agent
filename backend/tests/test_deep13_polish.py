"""深度十三期测试：记账准确性 / 重试分类 / 规划上下文 / 转写窗口 / purge 清理 / 媒体鉴权。"""
import hashlib
import io

import pytest
from PIL import Image

import app.llm.client as llm_module
from app.core.config import settings
from app.core.database import SessionLocal
from app.api.chat import run_agent
from app.llm.client import LLMError, client as llm_client
from app.models import Asset, DocumentChunk
from app.retrieval.bm25 import tokenize
from app.retrieval.chunk_vector import chunk_vector_store


def _png(name="t.png"):
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), color=(20, 90, 140)).save(buf, format="PNG")
    buf.seek(0)
    return name, buf.read(), "image/png"


def _bag_vectors(texts):
    out = []
    for t in texts:
        v = [0.0] * 64
        for tok in tokenize(t):
            v[hashlib.md5(tok.encode("utf-8")).digest()[0] % 64] = 1.0
        out.append(v)
    return out


# ---------- 记账：只有真实发生的模型调用才记录 ----------

def test_degraded_upload_records_no_usage(client):
    """无 Key 降级模式：上传成功但没有任何真实模型调用，不消耗配额。"""
    r = client.post("/api/upload", files={"files": _png("静音图.png")})
    assert r.json()["items"][0]["asset"]["status"] == "ready"
    summary = client.get("/api/usage/summary").json()
    assert summary["total_calls"] == 0


# ---------- LLM 重试分类：429/5xx 退避重试，其余 4xx 立即失败 ----------

def test_llm_retry_classifies_errors(monkeypatch):
    monkeypatch.setattr(llm_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm_client.settings, "llm_max_retries", 3)

    class Resp:
        def __init__(self, status):
            self.status_code = status
            self.text = "boom"

    calls = []
    monkeypatch.setattr(llm_module.httpx, "post", lambda *a, **k: calls.append(1) or Resp(401))
    with pytest.raises(LLMError):
        llm_client._post("http://x", {}, {})
    assert len(calls) == 1  # 鉴权错误不重试

    calls.clear()
    monkeypatch.setattr(llm_module.httpx, "post", lambda *a, **k: calls.append(1) or Resp(429))
    with pytest.raises(LLMError):
        llm_client._post("http://x", {}, {})
    assert len(calls) == 3  # 限流重试至上限


# ---------- Agent 规划带上最近几轮对话 ----------

def test_planner_receives_conversation_history(client, monkeypatch):
    run_agent("帮我搜夜景", "hist-planner")

    calls = []

    def fake_chat(messages, temperature=0.3, max_tokens=800):
        calls.append(messages)
        return None  # 规划退回规则兜底，不影响断言

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    run_agent("再来几张蓝色的", "hist-planner")

    planner_calls = [m for m in calls if m and "任务规划器" in m[0]["content"]]
    assert planner_calls
    planner_messages = planner_calls[0]
    contents = [m["content"] for m in planner_messages]
    assert "帮我搜夜景" in contents  # 上一轮用户消息进入了规划上下文
    assert planner_messages[0]["role"] == "system"
    assert planner_messages[-1] == {"role": "user", "content": "再来几张蓝色的"}


# ---------- 转写窗口覆盖完整提取时长 ----------

def test_transcribe_covers_full_extraction_window(tmp_path, monkeypatch):
    import app.pipeline.processors as processors_module

    calls = []
    monkeypatch.setattr(llm_client, "transcribe_audio", lambda path: calls.append(1) or "内容")
    monkeypatch.setattr(processors_module, "_slice_audio", lambda src, start, duration, out: out)

    asset = Asset(
        id=1, name="长视频", original_filename="v.mp4", modality="video",
        mime_type="video/mp4", size_bytes=1, storage_path="uploads/video/v.mp4",
        sha256="asr-window-1", status="ready",
    )
    # 2 小时视频：音轨只提取前 600 秒，转写应覆盖这 600 秒（20 段），而不是被旧上限 10 段截断
    text, segments = processors_module._transcribe_segments(
        asset, llm_client, tmp_path / "a.wav", tmp_path, duration=7200.0
    )
    assert len(calls) == 20
    assert text == "内容 内容" or text.startswith("内容")
    assert segments[-1]["end"] == 600.0


# ---------- purge 彻底清理 chunk 向量与行 ----------

def test_purge_cleans_chunks_and_chunk_vectors(client, monkeypatch):
    monkeypatch.setattr(llm_client, "embed_texts", _bag_vectors)
    long_doc = ("第一段讲多模态检索的架构设计。\n\n" * 100)
    r = client.post("/api/upload", files={"files": ("长文.txt", long_doc.encode("utf-8"), "text/plain")})
    aid = r.json()["items"][0]["asset"]["id"]
    assert len(chunk_vector_store.keys(settings.embedding_model)) >= 2

    assert client.delete(f"/api/assets/{aid}").status_code == 200  # 软删除进回收站
    assert client.delete(f"/api/assets/trash/{aid}").status_code == 200  # 彻底删除

    assert len(chunk_vector_store.keys(settings.embedding_model)) == 0
    with SessionLocal() as db:
        assert db.query(DocumentChunk).filter(DocumentChunk.asset_id == aid).count() == 0
        assert db.get(Asset, aid) is None


# ---------- 媒体接口：格式异常的 Authorization 返回 401 而非 500 ----------

def test_media_malformed_auth_header_returns_401(client):
    r = client.get("/media/uploads/image/none.png", headers={"Authorization": "Bearer"})
    assert r.status_code == 401
