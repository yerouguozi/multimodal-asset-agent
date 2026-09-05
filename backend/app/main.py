"""应用入口：FastAPI + 生命周期（建表/启动 worker）+ 静态资源。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.config import BASE_DIR, settings
from .core.database import init_db
from .pipeline.manager import manager

STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await manager.start()
    yield
    await manager.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .api import assets, auth, chat, domain, jobs, metrics, qc, search, upload, usage  # noqa: E402

app.include_router(upload.router)
app.include_router(domain.router)
app.include_router(chat.router)
app.include_router(usage.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(qc.router)
app.include_router(assets.router)
app.include_router(search.router)
app.include_router(jobs.router)

# /static 提供内置演示页
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/media/{file_path:path}")
async def protected_media(
    file_path: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    """素材/缩略图访问：JWT（Header 或 ?token=）+ owner 校验。

    图片/视频标签无法带自定义头，前端会以 ?token= 方式访问；
    未登录视为 local 访客，只能访问访客自己的素材。
    """
    import jwt as pyjwt

    from .core.config import BASE_DIR, settings as app_settings
    from .core.database import SessionLocal
    from .models import Asset, User

    owner = "local"
    auth_value = authorization or (f"Bearer {token}" if token else None)
    if auth_value:
        parts = auth_value.split(" ", 1)
        if len(parts) != 2 or not parts[1].strip():
            raise HTTPException(401, "token 无效或过期")
        token_str = parts[1].strip()
        try:
            payload = pyjwt.decode(token_str, settings.jwt_secret, algorithms=["HS256"])
        except pyjwt.PyJWTError:
            raise HTTPException(401, "token 无效或过期")
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == payload.get("sub", "")).first()
        if user is None:
            raise HTTPException(401, "用户不存在")
        owner = user.username
    raw = str(file_path).replace("\\", "/")
    full = (app_settings.data_dir / raw).resolve()
    data_root = app_settings.data_dir.resolve()
    if not full.is_relative_to(data_root):
        raise HTTPException(404, "文件不存在")
    rel = full.relative_to(data_root).as_posix()
    with SessionLocal() as db:
        asset = (
            db.query(Asset)
            .filter(
                Asset.owner == owner,
                ((Asset.storage_path == rel) | (Asset.thumbnail_path == rel)),
                Asset.deleted_at.is_(None),
            )
            .first()
        )
    if asset is None:
        raise HTTPException(404, "文件不存在或无权访问")
    if not full.is_file():
        raise HTTPException(404, "文件不存在")
    import mimetypes

    mime = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
    return FileResponse(str(full), media_type=mime, filename=full.name)
