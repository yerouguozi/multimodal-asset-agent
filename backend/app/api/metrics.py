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
            "by_strategy": {},
            "gate": {},
            "top_queries": [],
            "recent": [],
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
    by_strategy: Counter[str] = Counter(r.strategy or "full" for r in rows)
    # 门控决策分布：method=vector|keyword 是真实判定，always_on/disabled 是策略直通
    gate_rows = [r for r in rows if r.gate_method]
    margins = sorted(r.gate_margin for r in gate_rows if r.gate_margin is not None)
    decided = [r for r in gate_rows if r.gate_visual is not None and r.gate_method in ("vector", "keyword")]
    gate = {
        "by_method": dict(Counter(r.gate_method for r in gate_rows)),
        "visual_ratio": round(sum(1 for r in decided if r.gate_visual) / len(decided), 3) if decided else None,
        "avg_margin": round(sum(margins) / len(margins), 4) if margins else None,
    }
    recent = [
        {
            "created_at": r.created_at.isoformat(),
            "query": r.query,
            "source": r.source,
            "strategy": r.strategy or "full",
            "latency_ms": r.latency_ms,
            "hits_count": r.hits_count,
            "gate_method": r.gate_method or "",
            "gate_margin": r.gate_margin,
        }
        for r in rows[-15:]
    ]
    return {
        "total_queries": len(rows),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
        "p95_latency_ms": _p95(latencies),
        "avg_hits": round(sum(hits) / len(hits), 2),
        "by_source": dict(by_source),
        "by_strategy": dict(by_strategy),
        "gate": gate,
        "top_queries": top_queries,
        "recent": recent,
    }
