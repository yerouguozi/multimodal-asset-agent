"""Agent 对话接口：SSE 逐步推送（规划 → 工具 → 回答）。

会话记忆落库（chat_sessions / chat_messages），重启不丢。
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent.graph import agent_app
from ..core.database import SessionLocal
from ..models import ChatMessage, ChatSession

router = APIRouter(prefix="/api", tags=["chat"])

HISTORY_LIMIT = 6


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _load_history(session_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_LIMIT)
            .all()
        )
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def _save_messages(session_id: str, messages: list[dict]) -> None:
    with SessionLocal() as db:
        if db.get(ChatSession, session_id) is None:
            db.add(ChatSession(id=session_id, title=session_id))
        for m in messages:
            db.add(ChatMessage(session_id=session_id, role=m["role"], content=m["content"]))
        db.commit()


def run_agent(message: str, session_id: str) -> tuple[str, list[dict], list[str]]:
    """同步执行 LangGraph 图，返回 (回答, 步骤列表, 工具名列表)。"""
    history = _load_history(session_id)
    input_state = {
        "messages": history + [{"role": "user", "content": message}],
        "plan": [],
        "step_index": 0,
        "results": [],
        "tool_result": {},
        "tool_used": None,
        "intent": "",
        "answer": "",
    }
    steps: list[dict] = []
    tool_names: list[str] = []
    answer = ""
    for update in agent_app.stream(input_state, stream_mode="updates"):
        for node, data in update.items():
            if node == "planner":
                steps.append({"stage": "intent", "content": f"意图识别：{data.get('intent', '')}"})
            elif node == "tool":
                steps.append({"stage": "tool", "content": data.get("tool_result", {}).get("summary", "")})
                tool = data.get("tool_used")
                if tool:
                    tool_names.append(tool)
            elif node == "answer":
                answer = data.get("answer", "")
    if answer:
        _save_messages(session_id, [
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ])
    return answer, steps, tool_names


@router.post("/chat")
async def chat(req: ChatRequest):
    message = (req.message or "").strip()
    session_id = req.session_id or "default"

    async def gen():
        if not message:
            yield _sse("error", {"text": "消息不能为空"})
            return
        yield _sse("meta", {"session_id": session_id})
        answer, steps, _ = await asyncio.to_thread(run_agent, message, session_id)
        for step in steps:
            yield _sse("step", step)
        yield _sse("answer", {"text": answer or "抱歉，我没有理解你的意思。"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
