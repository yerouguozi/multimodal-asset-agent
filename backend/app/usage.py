"""模型调用成本追踪（估算值，用于展示"成本意识"而非精确计费）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter

from fastapi import HTTPException

from .core.config import settings
from .core.database import SessionLocal
from .models import Asset, UsageLog


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# 每次“用户操作”预计触发的模型调用数（配额按操作预检）
ESTIMATED_CALLS: dict[str, int] = {
    "image": 3,
    "video": 4,
    "audio": 4,
    "document": 2,
    "chat": 3,
    "image_search": 2,
}

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


def quota_usage(db, owner: str) -> dict:
    """返回该用户在今日 / 本月 / 近 1 小时内的实际调用数。"""
    now = _utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    hour_start = now - timedelta(hours=1)
    q = db.query(UsageLog).filter(UsageLog.owner == owner)
    return {
        "today": q.filter(UsageLog.created_at >= day_start).count(),
        "month": q.filter(UsageLog.created_at >= month_start).count(),
        "hour": q.filter(UsageLog.created_at >= hour_start).count(),
    }


def ensure_quota(owner: str, estimated: int = 1) -> bool:
    """预检配额；超限抛 429（用于上传/以图搜图/对话等会触发模型的入口）。"""
    if estimated <= 0:
        return True
    with SessionLocal() as db:
        used = quota_usage(db, owner)
    if used["today"] + estimated > settings.usage_daily_limit:
        raise HTTPException(429, "今日模型调用配额已用尽，请明天再试或提高 USAGE_DAILY_LIMIT")
    if used["month"] + estimated > settings.usage_monthly_limit:
        raise HTTPException(429, "本月模型调用配额已用尽")
    if used["hour"] + estimated > settings.usage_hourly_limit:
        raise HTTPException(429, "请求过于频繁，请稍后再试")
    return True


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
    out = {
        "total_calls": len(rows),
        "total_cost": round(total_cost, 4),
        "by_model": dict(by_model),
        "recent": [
            {"asset_id": r.asset_id, "model": r.model, "operation": r.operation,
             "cost": r.cost_estimate, "created_at": r.created_at.isoformat()}
            for r in rows[:10]
        ],
    }
    if owner:
        used = quota_usage(db, owner)
        out["quota"] = {
            "daily": {"used": used["today"], "limit": settings.usage_daily_limit,
                      "remaining": max(0, settings.usage_daily_limit - used["today"])},
            "monthly": {"used": used["month"], "limit": settings.usage_monthly_limit,
                        "remaining": max(0, settings.usage_monthly_limit - used["month"])},
            "hourly": {"used": used["hour"], "limit": settings.usage_hourly_limit,
                       "remaining": max(0, settings.usage_hourly_limit - used["hour"])},
        }
    return out
