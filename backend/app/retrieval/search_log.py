"""检索日志落库（供延迟/命中率可观测）。"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models import SearchLog


def record_search(
    db: Session,
    *,
    owner: str,
    query: str,
    source: str = "api",
    hits_count: int = 0,
    latency_ms: int = 0,
    modality: str = "",
    strategy: str = "full",
    top_ids: list[int] | None = None,
) -> None:
    db.add(
        SearchLog(
            owner=owner,
            query=(query or "")[:500],
            modality=modality[:20],
            source=source,
            strategy=strategy[:20],
            hits_count=int(hits_count),
            latency_ms=int(latency_ms),
            top_ids=json.dumps(top_ids or [], ensure_ascii=False)[:2000],
        )
    )
    db.commit()
