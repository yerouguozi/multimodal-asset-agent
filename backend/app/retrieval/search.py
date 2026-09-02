"""检索服务（阶段 1 版本）。

当前：关键词匹配（名称/描述/OCR/转录/正文）+ 向量相似度（有 embedding 时）加权融合；
阶段 3 将升级为 BM25 + RRF 混合 + 重排，并接入评测集量化对比。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from ..llm.client import client as llm_client
from ..models import Asset, Tag
from .vector_store import vector_store

logger = logging.getLogger(__name__)

_TOKEN_SPLIT = re.compile(r"[\s,，。、;；:：/\\|]+")


def _keyword_score(query: str, tokens: list[str], asset: Asset) -> float:
    fields = " ".join(
        filter(
            None,
            [
                asset.name,
                asset.original_filename,
                asset.description,
                asset.ocr_text,
                asset.transcript,
                asset.text_content,
            ],
        )
    )
    low = fields.lower()
    ql = query.lower()
    score = 0.0
    if ql and ql in low:
        score += 2.0
    for tok in tokens:
        if len(tok) >= 2 and tok.lower() in low:
            score += 1.0
    return score


def search(
    db: Session,
    query: str,
    modality: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[tuple[Asset, float]]:
    """返回 [(asset, score)]，按分数降序。"""
    query = (query or "").strip()
    if not query:
        return []

    assets = db.query(Asset).filter(Asset.status == "ready").all()
    if not assets:
        return []

    tokens = [t for t in _TOKEN_SPLIT.split(query) if t]

    # 向量召回（有 embedding + 库非空时启用）
    vec_hits: dict[int, float] = {}
    if len(vector_store) > 0:
        try:
            vecs = llm_client.embed_texts([query])
            if vecs:
                vec_hits = vector_store.search(vecs[0], top_k=50)
        except Exception as e:
            logger.warning("向量检索失败，退回关键词: %s", e)

    results: list[tuple[float, Asset]] = []
    for asset in assets:
        if modality and asset.modality != modality:
            continue
        if tag and not any(t.name == tag for t in asset.tags):
            continue
        kw = _keyword_score(query, tokens, asset)
        vsim = vec_hits.get(asset.id, 0.0)
        score = kw + vsim
        if score > 0:
            results.append((score, asset))

    results.sort(key=lambda x: -x[0])
    return [(asset, score) for score, asset in results[:limit]]
