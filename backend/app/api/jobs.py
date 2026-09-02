"""处理进度查询。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import Asset, IngestionJob
from ..schemas import JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{asset_id}", response_model=JobOut)
def job_status(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "素材不存在")
    job = db.query(IngestionJob).filter(IngestionJob.asset_id == asset_id).order_by(IngestionJob.id.desc()).first()
    if job is None:
        raise HTTPException(404, "尚无处理任务")
    return job
