"""语义检索接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..retrieval import search as search_service
from ..schemas import AssetOut, SearchHit, SearchResponse

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str,
    modality: str | None = None,
    tag: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    hits = search_service.search(db, q, modality=modality, tag=tag, limit=limit)
    return SearchResponse(
        query=q,
        hits=[SearchHit(asset=AssetOut.model_validate(a), score=round(s, 4)) for a, s in hits],
    )
