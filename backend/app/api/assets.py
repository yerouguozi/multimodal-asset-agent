"""素材管理：列表 / 详情 / 改标签 / 删除 / 批量打包下载。"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth import resolve_owner
from ..core.config import settings
from ..core.database import SessionLocal, get_db
from ..models import Asset, DocumentChunk, IngestionJob, Tag, utcnow
from ..pipeline.manager import manager
from ..retrieval.chunk_vector import chunk_vector_store
from ..retrieval.vector_store import vector_store
from ..schemas import AssetListOut, AssetOut, AssetPatch, AssetStatsOut
from ..usage import ESTIMATED_CALLS, ensure_quota


class DownloadZipBody(BaseModel):
    ids: list[int] = []


def _safe_zip_name(asset: Asset) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", asset.original_filename or asset.name)
    return f"{asset.id}_{name[:120]}"


router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("/download-zip")
def download_zip(body: DownloadZipBody, owner: str = Depends(resolve_owner)):
    """把选中的原始文件打包下载（仅限当前用户自己的素材）。"""
    ids = list(dict.fromkeys(body.ids))[:200]
    if not ids:
        raise HTTPException(400, "请先选择素材")
    with SessionLocal() as db:
        assets = (
            db.query(Asset)
            .filter(Asset.id.in_(ids), Asset.owner == owner, Asset.status == "ready")
            .filter(Asset.deleted_at.is_(None))
            .all()
        )
        if not assets:
            raise HTTPException(404, "没有可下载的素材")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for a in assets:
                p = settings.data_dir / a.storage_path
                try:
                    if p.is_file() and p.resolve().is_relative_to(settings.data_dir.resolve()):
                        zf.write(p, _safe_zip_name(a))
                except OSError:
                    continue
    data = buf.getvalue()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="assets.zip"'},
    )


@router.get("/trash")
def list_trash(db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    items = (
        db.query(Asset)
        .filter(Asset.owner == owner, Asset.deleted_at.is_not(None))
        .order_by(Asset.deleted_at.desc())
        .all()
    )
    return {"items": [AssetOut.model_validate(a) for a in items], "total": len(items)}


@router.post("/trash/{asset_id}/restore", response_model=AssetOut)
def restore_asset(asset_id: int, db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.owner == owner, Asset.deleted_at.is_not(None))
        .first()
    )
    if asset is None:
        raise HTTPException(404, "回收站中没有该素材")
    asset.deleted_at = None
    db.commit()
    db.expire_all()
    return db.query(Asset).filter(Asset.id == asset_id).first()


@router.delete("/trash/{asset_id}")
def purge_asset(asset_id: int, db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    """彻底删除：移除磁盘文件、素材与 chunk 向量、分块与任务记录，不可恢复。"""
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.owner == owner, Asset.deleted_at.is_not(None))
        .first()
    )
    if asset is None:
        raise HTTPException(404, "回收站中没有该素材")
    chunk_ids = [
        row[0]
        for row in db.query(DocumentChunk.id).filter(DocumentChunk.asset_id == asset_id).all()
    ]
    for rel in (asset.storage_path, asset.thumbnail_path):
        if not rel:
            continue
        p = settings.data_dir / rel
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    vector_store.delete(asset_id)
    chunk_vector_store.delete_ids(chunk_ids)
    # chunk/任务行没有级联关系，显式清掉避免孤儿数据累积（UsageLog 保留作成本历史）
    db.query(DocumentChunk).filter(DocumentChunk.asset_id == asset_id).delete(synchronize_session=False)
    db.query(IngestionJob).filter(IngestionJob.asset_id == asset_id).delete(synchronize_session=False)
    db.delete(asset)
    db.commit()
    return {"ok": True, "id": asset_id}


@router.get("", response_model=AssetListOut)
def list_assets(
    modality: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    q = db.query(Asset).filter(Asset.owner == owner)
    q = q.filter(Asset.deleted_at.is_not(None)) if deleted else q.filter(Asset.deleted_at.is_(None))
    if modality:
        q = q.filter(Asset.modality == modality)
    if status:
        q = q.filter(Asset.status == status)
    if tag:
        q = q.join(Asset.tags).filter(Tag.name == tag)
    total = q.count()
    items = q.order_by(Asset.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return AssetListOut(
        items=[AssetOut.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.owner == owner, Asset.deleted_at.is_(None))
        .first()
    )
    if asset is None:
        raise HTTPException(404, "素材不存在")
    return asset


@router.get("/{asset_id}/segments")
def get_asset_segments(
    asset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    """返回音视频转写片断（供播放器时间戳跳转）。"""
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.owner == owner, Asset.deleted_at.is_(None))
        .first()
    )
    if asset is None:
        raise HTTPException(404, "素材不存在")
    try:
        segments = json.loads(asset.transcript_segments or "[]")
    except Exception:
        segments = []
    return {
        "asset_id": asset.id,
        "modality": asset.modality,
        "duration": asset.duration,
        "segments": [
            {"start": s.get("start", 0), "end": s.get("end"), "text": s.get("text", "")}
            for s in segments
        ],
    }


@router.patch("/{asset_id}", response_model=AssetOut)
def patch_asset(
    asset_id: int,
    body: AssetPatch,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.owner == owner, Asset.deleted_at.is_(None))
        .first()
    )
    if asset is None:
        raise HTTPException(404, "素材不存在")
    if body.name is not None and body.name.strip():
        asset.name = body.name.strip()[:255]
    if body.description is not None:
        asset.description = body.description.strip()[:5000] or None
    for name in body.add_tags:
        name = name.strip()
        if not name:
            continue
        if not any(t.name == name for t in asset.tags):
            db.add(Tag(asset_id=asset.id, name=name, source="user"))
    db.flush()
    remove = {n.strip() for n in body.remove_tags if n.strip()}
    if remove:
        db.query(Tag).filter(
            Tag.asset_id == asset_id,
            Tag.name.in_(remove),
        ).delete(synchronize_session=False)
    db.commit()
    db.expire_all()
    fresh = db.query(Asset).filter(Asset.id == asset_id, Asset.owner == owner).first()
    return fresh or asset


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.owner == owner).first()
    if asset is None:
        raise HTTPException(404, "素材不存在")
    # 软删除：先进回收站（文件与向量保留，恢复零成本）
    asset.deleted_at = utcnow()
    db.commit()
    return {"ok": True, "id": asset_id, "trashed": True}


@router.post("/{asset_id}/retry", response_model=AssetOut)
async def retry_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.owner == owner, Asset.deleted_at.is_(None))
        .first()
    )
    if asset is None:
        raise HTTPException(404, "素材不存在")
    if asset.status != "failed":
        raise HTTPException(400, "仅失败素材可重试")
    ensure_quota(owner, ESTIMATED_CALLS.get(asset.modality, 1))
    asset.status = "pending"
    asset.error_message = None
    db.commit()
    try:
        await manager.submit(asset_id)
    except Exception as e:
        asset.status = "failed"
        asset.error_message = f"重试入队失败: {e}"
        db.commit()
        raise HTTPException(500, f"重试入队失败: {e}")
    db.expire_all()
    return db.query(Asset).filter(Asset.id == asset_id).first()


@router.get("/stats/overview", response_model=AssetStatsOut)
def stats(db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    from collections import Counter

    assets = (
        db.query(Asset)
        .filter(Asset.owner == owner, Asset.deleted_at.is_(None))
        .all()
    )
    by_modality = Counter(a.modality for a in assets)
    by_status = Counter(a.status for a in assets)
    tag_counter: Counter[str] = Counter()
    for asset in assets:
        for t in asset.tags:
            tag_counter[t.name] += 1
    return AssetStatsOut(
        total=len(assets),
        by_modality=dict(by_modality),
        by_status=dict(by_status),
        top_tags=[{"name": k, "count": v} for k, v in tag_counter.most_common(20)],
    )
