"""上传接口：检测模态 → SHA-256 去重 → 落盘 → 入队处理。"""
from __future__ import annotations

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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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

        content = await f.read()
        if not content:
            items.append(UploadItem(error=f"空文件: {f.filename}"))
            continue

        digest = _sha256(content)
        existing = (
            db.query(Asset)
            .filter(Asset.sha256 == digest, Asset.owner == owner, Asset.deleted_at.is_(None))
            .first()
        )
        if existing:
            items.append(UploadItem(duplicate_of=existing.id))
            continue

        ext = _safe_ext(f.filename or "file")
        storage_name = f"{uuid.uuid4().hex}{ext}"
        rel_dir = Path(settings.upload_dir).name
        rel_path = f"{rel_dir}/{modality}/{storage_name}"
        target = settings.upload_path / modality / storage_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

        asset = Asset(
            owner=owner,
            name=Path(f.filename or storage_name).stem[:120],
            original_filename=f.filename or storage_name,
            modality=modality,
            mime_type=f.content_type or "",
            size_bytes=len(content),
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
