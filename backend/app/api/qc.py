"""兼容 agent-qc-platform CustomerServiceDriver 的评测接入接口。

协议（见质控平台 app/eval/driver.py）：
  POST /api/sessions  {"title": ...}         -> {"id": sid}
  POST /api/sessions/{sid}/messages {"content": prompt} -> [{"content": 回答, "tool_calls": [...]}]
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from .chat import run_agent

router = APIRouter(prefix="/api", tags=["qc"])

_sessions: dict[str, dict] = {}


class SessionCreate(BaseModel):
    title: str = "qc-eval"


class MessageBody(BaseModel):
    content: str = ""


@router.post("/sessions")
def create_session(body: SessionCreate, user=Depends(get_current_user)):
    sid = f"qc-{uuid.uuid4().hex[:10]}"
    _sessions[sid] = {"title": body.title}
    return {"id": sid}


@router.post("/sessions/{sid}/messages")
def send_message(sid: str, body: MessageBody, user=Depends(get_current_user)):
    if sid not in _sessions:
        raise HTTPException(404, "会话不存在")
    message = (body.content or "").strip()
    if not message:
        raise HTTPException(400, "消息不能为空")
    answer, _steps, tool_names = run_agent(message, sid)
    return [{"content": answer or "", "tool_calls": [{"name": n} for n in tool_names]}]
