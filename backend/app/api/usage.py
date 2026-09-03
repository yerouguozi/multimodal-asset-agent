"""模型调用成本追踪接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .auth import resolve_owner
from ..core.database import get_db
from ..usage import usage_summary

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    return usage_summary(db, owner=owner)
