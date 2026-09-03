"""模型调用成本追踪（估算值，用于展示"成本意识"而非精确计费）。"""
from __future__ import annotations

from collections import Counter

from .core.database import SessionLocal
from .models import Asset, UsageLog

# 按"每次调用"的估算单价（美元），仅供演示与成本对比
PRICE_PER_CALL: dict[str, float] = {
    "Qwen/Qwen3-VL-32B-Instruct": 0.02,
    "Qwen/Qwen3-VL-8B-Instruct": 0.005,
    "BAAI/bge-m3": 0.001,
    "BAAI/bge-reranker-v2-m3": 0.001,
    "FunAudioLLM/SenseVoiceSmall": 0.002,
    "Qwen/Qwen-Image": 0.05,
    "deepseek-v4-pro": 0.01,
    "deepseek-chat": 0.01,
}


def estimate_cost(model: str) -> float:
    return PRICE_PER_CALL.get(model, 0.0)


def record_usage(
    asset_id: int | None,
    model: str,
    operation: str,
    owner: str | None = None,
) -> None:
    """独立开事务记录一次模型调用，归属到素材 owner（无素材时显式传 owner）。"""
    if not model:
        return
    with SessionLocal() as db:
        if owner is None and asset_id is not None:
            asset = db.get(Asset, asset_id)
            if asset is not None:
                owner = asset.owner
        db.add(
            UsageLog(
                owner=owner or "local",
                asset_id=asset_id,
                model=model,
                operation=operation,
                cost_estimate=estimate_cost(model),
            )
        )
        db.commit()


def usage_summary(db, owner: str | None = None) -> dict:
    q = db.query(UsageLog)
    if owner:
        q = q.filter(UsageLog.owner == owner)
    rows = q.order_by(UsageLog.id.desc()).all()
    by_model: Counter[str] = Counter()
    total_cost = 0.0
    for r in rows:
        by_model[r.model] += 1
        total_cost += r.cost_estimate
    return {
        "total_calls": len(rows),
        "total_cost": round(total_cost, 4),
        "by_model": dict(by_model),
        "recent": [
            {"asset_id": r.asset_id, "model": r.model, "operation": r.operation,
             "cost": r.cost_estimate, "created_at": r.created_at.isoformat()}
            for r in rows[:10]
        ],
    }
