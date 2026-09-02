"""深度二期(2)测试：会话记忆落库 / 多步规划 / 时间戳转写 / 以图搜图 / Milvus 接口。"""
import io
import json
import math
import struct
import wave

import pytest
from PIL import Image

from app.agent.tools import find_moment
from app.core.config import settings
from app.llm.client import VisionResult, client as llm_client
from app.models import Asset, ChatMessage
from app.pipeline.processors import process_audio


def upload_png(client, name):
    buf = io.BytesIO()
    seed = sum(ord(c) for c in name)
    Image.new("RGB", (64, 48), color=(30 + seed % 180, 80, 160)).save(buf, format="PNG")
    buf.seek(0)
    return client.post("/api/upload", files={"files": (name, buf.read(), "image/png")})


def make_wav(path, seconds):
    rate = 8000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        )
        w.writeframes(frames)


def make_audio_asset(storage_path):
    return Asset(
        id=1, name="a", original_filename="a.wav", modality="audio",
        mime_type="audio/wav", size_bytes=1, storage_path=storage_path,
        sha256="x", status="pending",
    )


# ---------- 会话记忆落库 ----------

def test_chat_memory_persists(client):
    from app.api.chat import run_agent
    from app.core.database import SessionLocal

    run_agent("帮我搜夜景", "mem-1")
    run_agent("再帮我看看 #1", "mem-1")
    with SessionLocal() as db:
        rows = db.query(ChatMessage).filter(ChatMessage.session_id == "mem-1").all()
        assert len(rows) == 4
        assert rows[-1].role == "assistant"


# ---------- 多步规划 ----------

def test_agent_multi_step_plan(client, monkeypatch):
    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b, m, model=None: VisionResult(description="夜景", tags=["夜景"], ocr=""),
    )
    upload_png(client, "n.png")

    from app.agent.graph import agent_app

    def fake_chat(messages, temperature=0.3, max_tokens=800):
        system = messages[0]["content"]
        if "任务规划器" in system:
            return '{"steps": [{"tool": "search_assets", "args": {"query": "夜景"}}, {"tool": "get_asset_detail", "args": {"asset_id": 1}}]}'
        return "完成两步操作。"

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    result = agent_app.invoke({
        "messages": [{"role": "user", "content": "搜夜景然后看看第一个"}],
        "plan": [], "step_index": 0, "results": [],
        "tool_result": {}, "tool_used": None, "intent": "", "answer": "",
    })
    assert len(result["results"]) == 2
    assert result["results"][0]["assets"][0]["name"] == "n"
    assert result["answer"] == "完成两步操作。"


# ---------- 时间戳分片转写 ----------

def test_audio_transcript_segments(tmp_path, monkeypatch):
    src = tmp_path / "uploads" / "audio" / "a.wav"
    src.parent.mkdir(parents=True)
    make_wav(src, 35)
    monkeypatch.setattr(llm_client, "transcribe_audio", lambda path: "这是第一段音频的内容")
    monkeypatch.setattr(llm_client, "summarize_text", lambda text: None)

    asset = make_audio_asset("uploads/audio/a.wav")
    result = process_audio(asset, llm_client, tmp_path)
    segs = json.loads(result.transcript_segments)
    assert len(segs) == 2
    assert segs[0]["start"] == 0.0
    assert segs[1]["start"] == 30.0
    assert "内容" in result.transcript


def test_find_moment_tool(client):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        db.add(Asset(
            name="会议录音", original_filename="m.mp3", modality="audio",
            mime_type="audio/mpeg", size_bytes=1, storage_path="uploads/audio/m.mp3",
            sha256="m1", status="ready",
            transcript_segments=json.dumps(
                [{"start": 65.0, "end": 95.0, "text": "下个季度重点是增长与留存"}], ensure_ascii=False
            ),
        ))
        db.commit()
    result = find_moment("增长")
    assert result["ok"] is True
    assert result["moments"][0]["start"] == 65.0


def test_transcript_search_api(client):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        db.add(Asset(
            name="会议录音", original_filename="m.mp3", modality="audio",
            mime_type="audio/mpeg", size_bytes=1, storage_path="uploads/audio/m.mp3",
            sha256="m2", status="ready",
            transcript_segments=json.dumps(
                [{"start": 10.0, "end": 40.0, "text": "增长与留存是重点"}], ensure_ascii=False
            ),
        ))
        db.commit()
    r = client.get("/api/search/transcript", params={"q": "增长"})
    assert len(r.json()["hits"]) == 1
    assert r.json()["hits"][0]["start"] == 10.0


# ---------- 以图搜图 ----------

def test_search_by_image_api(client, monkeypatch):
    from app.retrieval.vector_store import vector_store

    r = upload_png(client, "ref.png")
    aid = r.json()["items"][0]["asset"]["id"]
    vec = [0.4] * 4096
    vector_store.add(aid, vec, settings.vl_embedding_model)
    monkeypatch.setattr(llm_client, "embed_image", lambda b64, mime="image/jpeg": vec)

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buf, "PNG")
    resp = client.post("/api/search/image", files={"file": ("q.png", buf.getvalue(), "image/png")})
    assert resp.status_code == 200
    hits = resp.json()["hits"]
    assert hits and hits[0]["asset"]["id"] == aid


# ---------- Milvus 接口 ----------

def test_milvus_store_importable():
    pytest.importorskip("pymilvus")
    from app.retrieval.milvus_store import MilvusVectorStore

    assert MilvusVectorStore is not None
