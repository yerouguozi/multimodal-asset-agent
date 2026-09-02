"""应用入口：FastAPI + 生命周期（建表/启动 worker）+ 静态资源。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
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

from .api import assets, jobs, search, upload  # noqa: E402

app.include_router(upload.router)
app.include_router(assets.router)
app.include_router(search.router)
app.include_router(jobs.router)

# /media 对外提供素材与缩略图（data 目录）
app.mount("/media", StaticFiles(directory=str(settings.data_dir)), name="media")
# /static 提供内置演示页
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
