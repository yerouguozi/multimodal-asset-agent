"""检索可观测指标：总量 / 平均与 P95 延迟 / 高频查询 / 来源分布。"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .auth import resolve_owner
from ..core.database import get_db
from ..models import SearchLog

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _p95(sorted_values: list[int]) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, int(round(len(sorted_values) * 0.95)) - 1)
    return float(sorted_values[idx])


@router.get("/search")
def search_metrics(db: Session = Depends(get_db), owner: str = Depends(resolve_owner)):
    rows = db.query(SearchLog).filter(SearchLog.owner == owner).all()
    if not rows:
        return {
            "total_queries": 0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "avg_hits": 0.0,
            "by_source": {},
            "top_queries": [],
        }
    latencies = sorted(r.latency_ms for r in rows)
    hits = [r.hits_count for r in rows]
    top_counter: Counter[str] = Counter()
    per_query = {q: [] for q in {r.query for r in rows}}
    for r in rows:
        top_counter[r.query] += 1
        per_query[r.query].append(r.latency_ms)
    top_queries = [
        {
            "query": q,
            "count": c,
            "avg_latency_ms": round(sum(per_query[q]) / len(per_query[q]), 1),
        }
        for q, c in top_counter.most_common(10)
    ]
    by_source: Counter[str] = Counter(r.source for r in rows)
    return {
        "total_queries": len(rows),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
        "p95_latency_ms": _p95(latencies),
        "avg_hits": round(sum(hits) / len(hits), 2),
        "by_source": dict(by_source),
        "top_queries": top_queries,
    }
