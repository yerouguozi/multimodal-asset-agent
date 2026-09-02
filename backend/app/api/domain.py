"""领域画像接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..domain.profile import build_profile
from ..schemas import DomainProfileOut

router = APIRouter(prefix="/api/domain", tags=["domain"])


@router.get("/profile", response_model=DomainProfileOut)
def domain_profile(db: Session = Depends(get_db)):
    p = build_profile(db)
    return {
        "total": p.total,
        "by_modality": p.by_modality,
        "modality_shares": p.modality_shares,
        "top_tags": [{"name": t, "count": c} for t, c in p.top_tags],
        "adaptive_weights": p.adaptive_weights,
        "labels": p.labels,
        "summary": p.summary,
    }
