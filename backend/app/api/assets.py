"""素材管理：列表 / 详情 / 改标签 / 删除。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import resolve_owner
from ..core.database import get_db
from ..models import Asset, Tag
from ..retrieval.vector_store import vector_store
from ..schemas import AssetListOut, AssetOut, AssetPatch, AssetStatsOut
from ..core.config import settings
from pathlib import Path

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("", response_model=AssetListOut)
def list_assets(
    modality: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    q = db.query(Asset).filter(Asset.owner == owner)
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
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.owner == owner).first()
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
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.owner == owner).first()
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
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.owner == owner).first()
    if asset is None:
        raise HTTPException(404, "素材不存在")
    for name in body.add_tags:
        name = name.strip()
        if not name:
            continue
        if not any(t.name == name for t in asset.tags):
            db.add(Tag(asset_id=asset.id, name=name, source="user"))
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.owner == owner).first()
    if asset is None:
        raise HTTPException(404, "素材不存在")
    # 删除磁盘文件
    for rel in (asset.storage_path, asset.thumbnail_path):
        if not rel:
            continue
        p = settings.data_dir / rel
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    vector_store.delete(asset_id)
    db.delete(asset)
    db.commit()
    return {"ok": True, "id": asset_id}


@router.get("/stats/overview", response_model=AssetStatsOut)
def stats(db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    from collections import Counter

    assets = db.query(Asset).filter(Asset.owner == owner).all()
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
