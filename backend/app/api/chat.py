"""Agent 对话接口：SSE 逐步推送 + 会话历史管理。

执行过程实时可观测：planner/tool 节点跑完即推送结构化事件，而不是等整轮
Agent 跑完再回放，前端可以把「意图 → 规划 → 每一步工具 → 最终回答」渲染成
可交互轨迹（命中素材可直接点击查看详情）。

SSE 事件协议：
- meta    {session_id, title?}
- plan    {intent, steps: [{tool, args}]}              规划结果（LLM 或规则兜底）
- tool    {tool, ok, summary, assets?, moments?, elapsed_ms}  单个工具执行结果
- step    {stage, content}                             纯文本步骤（向后兼容）
- answer  {text}
- error   {text}

会话记忆落库（chat_sessions / chat_messages），并提供列表与历史读取接口，
前端可新建/切换会话实现多轮上下文延续。
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func

from ..agent.graph import agent_app
from ..agent.tools import owner_ctx
from ..core.config import settings
from ..core.database import SessionLocal
from ..models import ChatMessage, ChatSession
from ..usage import ESTIMATED_CALLS, ensure_quota, record_usage
from .auth import resolve_owner

router = APIRouter(prefix="/api", tags=["chat"])

HISTORY_LIMIT = 6


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _load_history(session_id: str, owner: str = "local") -> list[dict]:
    with SessionLocal() as db:
        session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.owner == owner).first()
        if session is None:
            return []
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_LIMIT)
            .all()
        )
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def _save_messages(session_id: str, messages: list[dict], owner: str = "local") -> None:
    with SessionLocal() as db:
        session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.owner == owner).first()
        if session is None:
            # 首条用户消息作为会话标题（前台新建会话时传随机 id）
            first = next((m["content"] for m in messages if m["role"] == "user"), "")
            db.add(ChatSession(id=session_id, owner=owner, title=(first or session_id)[:40]))
        for m in messages:
            db.add(ChatMessage(session_id=session_id, role=m["role"], content=m["content"]))
        db.commit()


def run_agent(
    message: str,
    session_id: str,
    emit: Callable[[str, dict], None] | None = None,
    owner: str = "local",
) -> tuple[str, list[dict], list[str]]:
    """同步执行 LangGraph 图，返回 (回答, 旧版步骤列表, 工具名列表)。

    传入 emit 后会在每个节点产出时同步回调（由调用方桥接到异步 SSE 队列），
    从而实现“跑一步推一步”的实时轨迹。
    """
    history = _load_history(session_id, owner)
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
    last_ts = time.perf_counter()
    token = owner_ctx.set(owner)
    try:
        for update in agent_app.stream(input_state, stream_mode="updates"):
            now = time.perf_counter()
            elapsed_ms = int((now - last_ts) * 1000)
            last_ts = now
            for node, data in update.items():
                if node == "planner":
                    intent = data.get("intent", "")
                    plan = data.get("plan", [])
                    step_item = {"stage": "intent", "content": f"意图识别：{intent}"}
                    steps.append(step_item)
                    if emit:
                        emit(
                            "plan",
                            {
                                "intent": intent,
                                "steps": [
                                    {"tool": s.get("tool"), "args": s.get("args", {})}
                                    for s in plan
                                ],
                                "elapsed_ms": elapsed_ms,
                            },
                        )
                        emit("step", step_item)
                elif node == "tool":
                    result = data.get("tool_result", {})
                    tool = data.get("tool_used")
                    summary = result.get("summary", "")
                    step_item = {"stage": "tool", "content": summary}
                    steps.append(step_item)
                    if tool:
                        tool_names.append(tool)
                    if emit:
                        emit(
                            "tool",
                            {
                                "tool": tool,
                                "ok": bool(result.get("ok")),
                                "summary": summary,
                                "assets": result.get("assets", []),
                                "moments": result.get("moments", []),
                                "passages": result.get("passages", []),
                                "labels": result.get("labels", []),
                                "by_modality": result.get("by_modality", {}),
                                "elapsed_ms": elapsed_ms,
                            },
                        )
                        emit("step", step_item)
                elif node == "answer":
                    answer = data.get("answer", "")
    finally:
        owner_ctx.reset(token)
    if answer:
        if emit:
            emit("answer", {"text": answer})
        _save_messages(session_id, [
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ], owner)
    return answer, steps, tool_names


@router.post("/chat")
async def chat(req: ChatRequest, owner: str = Depends(resolve_owner)):
    ensure_quota(owner, ESTIMATED_CALLS["chat"])
    message = (req.message or "").strip()
    session_id = req.session_id or "default"

    async def gen():
        if not message:
            yield _sse("error", {"text": "消息不能为空"})
            return
        yield _sse("meta", {"session_id": session_id})

        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(event: str, data: dict) -> None:
            # run_agent 在线程里同步执行，事件经线程安全队列送回事件循环
            loop.call_soon_threadsafe(queue.put_nowait, {"event": event, "data": data})

        async def worker() -> None:
            try:
                answer, _, _ = await asyncio.to_thread(run_agent, message, session_id, emit, owner)
                if answer:
                    record_usage(None, settings.llm_model, "chat", owner=owner)
            except Exception as e:  # noqa: BLE001 - 网络边界，需兜底
                emit("error", {"text": f"Agent 执行失败：{e}"})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item["event"], item["data"])
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/sessions")
def list_sessions(owner: str = Depends(resolve_owner)):
    """会话列表（含消息数与最后一条消息，按最近活跃排序）。"""
    with SessionLocal() as db:
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.owner == owner)
            .order_by(ChatSession.created_at.desc())
            .limit(50)
            .all()
        )
        out = []
        for s in sessions:
            count = (
                db.query(func.count(ChatMessage.id))
                .filter(ChatMessage.session_id == s.id)
                .scalar()
                or 0
            )
            last = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == s.id)
                .order_by(ChatMessage.id.desc())
                .first()
            )
            out.append(
                {
                    "id": s.id,
                    "title": s.title or s.id,
                    "created_at": s.created_at.isoformat(),
                    "message_count": count,
                    "last_message": last.content[:160] if last else None,
                    "updated_at": last.created_at.isoformat() if last else s.created_at.isoformat(),
                }
            )
    return {"sessions": out}


@router.get("/chat/sessions/{session_id}/messages")
def get_session_messages(
    session_id: str,
    owner: str = Depends(resolve_owner),
):
    with SessionLocal() as db:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.owner == owner)
            .first()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
