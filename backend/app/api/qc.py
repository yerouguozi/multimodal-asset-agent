"""兼容 agent-qc-platform CustomerServiceDriver 的评测接入接口（会话落库）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.database import SessionLocal
from ..models import ChatSession
from .auth import get_current_user
from .chat import run_agent

router = APIRouter(prefix="/api", tags=["qc"])


class SessionCreate(BaseModel):
    title: str = "qc-eval"


class MessageBody(BaseModel):
    content: str = ""


@router.post("/sessions")
def create_session(body: SessionCreate, user=Depends(get_current_user)):
    sid = f"qc-{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        db.add(ChatSession(id=sid, title=body.title))
        db.commit()
    return {"id": sid}


@router.post("/sessions/{sid}/messages")
def send_message(sid: str, body: MessageBody, user=Depends(get_current_user)):
    with SessionLocal() as db:
        if db.get(ChatSession, sid) is None:
            raise HTTPException(404, "会话不存在")
    message = (body.content or "").strip()
    if not message:
        raise HTTPException(400, "消息不能为空")
    answer, _steps, tool_names = run_agent(message, sid)
    return [{"content": answer or "", "tool_calls": [{"name": n} for n in tool_names]}]
