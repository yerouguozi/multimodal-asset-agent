"""上传接口：检测模态 → SHA-256 去重 → 落盘 → 入队处理。"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .auth import resolve_owner
from ..core.config import settings
from ..core.database import get_db
from ..models import Asset
from ..pipeline.manager import manager
from ..schemas import AssetOut, UploadItem, UploadResult
from ..usage import ESTIMATED_CALLS, ensure_quota

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])

_UPLOAD_CHUNK = 1024 * 1024  # 流式写盘的分块大小

_EXT_MODALITY: dict[str, str] = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video", ".webm": "video",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".aac": "audio",
    ".flac": "audio", ".ogg": "audio",
    ".pdf": "document", ".docx": "document", ".doc": "document",
    ".xlsx": "document", ".xls": "document", ".txt": "document",
    ".md": "document", ".csv": "document", ".json": "document", ".log": "document",
}


def detect_modality(mime: str | None, filename: str) -> str | None:
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("text/") or mime in ("application/pdf", "application/msword",
                                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                "application/json", "text/csv"):
            return "document"
    return _EXT_MODALITY.get(Path(filename).suffix.lower())


def _safe_ext(filename: str) -> str:
    return Path(filename).suffix.lower()[:10]


async def _stream_to_disk(f: UploadFile, target: Path) -> tuple[Path, str, int]:
    """分块把上传流写进 .part 临时文件（不整读进内存），返回 (临时路径, sha256, 字节数)。

    超过 max_upload_mb 抛 413；写盘走线程池，避免阻塞事件循环。
    去重哈希在流式写入过程中顺带计算，因此去重判断移到落盘之后。
    """
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if f.size is not None and f.size > max_bytes:
        raise HTTPException(413, f"文件超过大小上限 {settings.max_upload_mb} MB")
    tmp = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    written = 0
    loop = asyncio.get_running_loop()
    fp = await loop.run_in_executor(None, tmp.open, "wb")
    try:
        while True:
            chunk = await f.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(413, f"文件超过大小上限 {settings.max_upload_mb} MB")
            digest.update(chunk)
            await loop.run_in_executor(None, fp.write, chunk)
    except BaseException:
        fp.close()
        tmp.unlink(missing_ok=True)
        raise
    await loop.run_in_executor(None, fp.close)
    return tmp, digest.hexdigest(), written


@router.post("/upload", response_model=UploadResult)
async def upload(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    estimated = sum(ESTIMATED_CALLS.get(detect_modality(f.content_type, f.filename or "") or "", 1) for f in files)
    ensure_quota(owner, estimated)
    items: list[UploadItem] = []
    for f in files:
        modality = detect_modality(f.content_type, f.filename or "")
        if modality is None:
            items.append(UploadItem(error=f"不支持的文件类型: {f.filename or ''}"))
            continue

        ext = _safe_ext(f.filename or "file")
        storage_name = f"{uuid.uuid4().hex}{ext}"
        rel_dir = Path(settings.upload_dir).name
        rel_path = f"{rel_dir}/{modality}/{storage_name}"
        target = settings.upload_path / modality / storage_name
        target.parent.mkdir(parents=True, exist_ok=True)

        # 流式落盘（先写 .part 临时文件），sha256 边写边算
        try:
            tmp, digest, size = await _stream_to_disk(f, target)
        except HTTPException as e:
            items.append(UploadItem(error=str(e.detail)))
            continue
        if size == 0:
            tmp.unlink(missing_ok=True)
            items.append(UploadItem(error=f"空文件: {f.filename}"))
            continue

        existing = (
            db.query(Asset)
            .filter(Asset.sha256 == digest, Asset.owner == owner, Asset.deleted_at.is_(None))
            .first()
        )
        if existing:
            tmp.unlink(missing_ok=True)
            items.append(UploadItem(duplicate_of=existing.id))
            continue

        tmp.replace(target)

        asset = Asset(
            owner=owner,
            name=Path(f.filename or storage_name).stem[:120],
            original_filename=f.filename or storage_name,
            modality=modality,
            mime_type=f.content_type or "",
            size_bytes=size,
            storage_path=rel_path,
            sha256=digest,
            status="pending",
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        try:
            await manager.submit(asset.id)
        except Exception as e:
            logger.exception("入队失败 asset_id=%s", asset.id)
            asset.status = "failed"
            asset.error_message = f"入队失败: {e}"
            db.commit()

        db.refresh(asset)
        items.append(UploadItem(asset=AssetOut.model_validate(asset)))
    return UploadResult(items=items)
