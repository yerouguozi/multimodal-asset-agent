"""极简 JWT 用户系统：注册/登录 + 鉴权依赖。

用途：质控平台等外部评测工具需要 SUT 提供 auth 接口。
密码用 pbkdf2_hmac 哈希，token 用 HS256 签名。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthBody(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return hmac.compare_digest(f"{salt.hex()}${dk.hex()}", stored)


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@router.post("/register", response_model=TokenOut)
def register(body: AuthBody, db: Session = Depends(get_db)):
    username = body.username.strip()
    if not username or len(body.password) < 4:
        raise HTTPException(400, "用户名不能为空，密码至少 4 位")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "用户已存在")
    db.add(User(username=username, password_hash=_hash_password(body.password)))
    db.commit()
    return TokenOut(access_token=create_token(username))


@router.post("/login", response_model=TokenOut)
def login(body: AuthBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip()).first()
    if user is None or not _verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    return TokenOut(access_token=create_token(user.username))


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "缺少 Authorization 头")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "token 无效或过期")
    user = db.query(User).filter(User.username == payload.get("sub", "")).first()
    if user is None:
        raise HTTPException(401, "用户不存在")
    return user


def resolve_owner(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    """数据所有者解析：无 token 视为本地访客 local；带 token 校验后返回用户名。

    这样既保留「不开账号也能本地体验」的降级路径，又让注册用户拿到真正的
    数据隔离（素材 / 检索 / 画像 / 会话都按 owner 过滤）。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return "local"
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "token 无效或过期")
    username = payload.get("sub", "")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(401, "用户不存在")
    return user.username


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"username": user.username}
