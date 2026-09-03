"""领域画像：数据驱动的素材库自我认知。

核心卖点：不预设分类，领域由已入库素材自动浮现——
模态分布 + 标签聚合 → LLM 生成领域名称与一句话总结；
同时输出检索字段的自适应权重（视频/音频占比高 → 转写权重更高）。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..llm.client import client as llm_client
from ..models import Asset

TOP_TAGS = 12


@dataclass
class DomainProfile:
    total: int = 0
    by_modality: dict[str, int] = field(default_factory=dict)
    modality_shares: dict[str, float] = field(default_factory=dict)
    top_tags: list[tuple[str, int]] = field(default_factory=list)
    adaptive_weights: dict[str, float] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    summary: str = ""


def build_profile(db: Session, owner: str | None = None) -> DomainProfile:
    q = db.query(Asset).filter(Asset.status == "ready", Asset.deleted_at.is_(None))
    if owner:
        q = q.filter(Asset.owner == owner)
    assets = q.all()
    profile = DomainProfile(total=len(assets))

    counts: Counter[str] = Counter(a.modality for a in assets)
    profile.by_modality = dict(counts)
    n = len(assets) or 1
    profile.modality_shares = {m: round(c / n, 3) for m, c in counts.items()}

    tag_counter: Counter[str] = Counter()
    for asset in assets:
        for t in asset.tags:
            tag_counter[t.name] += 1
    profile.top_tags = tag_counter.most_common(TOP_TAGS)

    video_share = profile.modality_shares.get("video", 0.0)
    audio_share = profile.modality_shares.get("audio", 0.0)
    profile.adaptive_weights = {
        "name": 2.0,
        "description": 1.2,
        "ocr": 0.8,
        "transcript": round(1.0 + 0.5 * video_share + 0.3 * audio_share, 3),
        "text_content": 1.0,
    }

    if n == 0:
        profile.summary = "素材库还是空的，上传素材后这里会自动长出领域画像。"
        return profile

    modality_desc = "、".join(f"{m} {c} 个" for m, c in counts.most_common())
    insight = llm_client.domain_insight(modality_desc, [t for t, _ in profile.top_tags])
    if insight:
        profile.labels = insight.labels
        profile.summary = insight.summary or ""
    else:
        dominant = counts.most_common(1)[0][0]
        tag_str = "、".join(t for t, _ in profile.top_tags[:5])
        profile.summary = f"目前共 {n} 个素材，以{dominant}为主，高频标签：{tag_str}。"
    return profile
