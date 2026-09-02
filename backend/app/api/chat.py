"""Agent 对话接口：SSE 逐步推送（意图 → 工具 → 回答）。

前端可以看到 Agent 的思考/行动过程，最终答案以 answer 事件给出。
"""
from __future__ import annotations

import asyncio
import json
from collections import deque

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent.graph import agent_app

router = APIRouter(prefix="/api", tags=["chat"])

# 轻量会话记忆：session_id -> 最近 6 条消息（进程内，MVP 足够）
SESSION_MEMORY: dict[str, deque] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_agent(message: str, session_id: str) -> tuple[str, list[dict], list[str]]:
    """同步执行 LangGraph 图，返回 (回答, 步骤列表, 工具名列表)。"""
    history = list(SESSION_MEMORY.get(session_id, deque(maxlen=6)))
    input_state = {
        "messages": history + [{"role": "user", "content": message}],
        "intent": "",
        "params": {},
        "tool_result": {},
        "answer": "",
    }
    steps: list[dict] = []
    tool_names: list[str] = []
    answer = ""
    for update in agent_app.stream(input_state, stream_mode="updates"):
        for node, data in update.items():
            if node == "intent":
                steps.append({"stage": "intent", "content": f"意图识别：{data.get('intent', '')}"})
            elif node == "tool":
                steps.append({"stage": "tool", "content": data.get("tool_result", {}).get("summary", "")})
                tool = data.get("tool_used")
                if tool:
                    tool_names.append(tool)
            elif node == "answer":
                answer = data.get("answer", "")
    if answer:
        mem = SESSION_MEMORY.setdefault(session_id, deque(maxlen=6))
        mem.append({"role": "user", "content": message})
        mem.append({"role": "assistant", "content": answer})
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
