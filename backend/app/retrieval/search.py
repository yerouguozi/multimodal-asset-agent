"""统一检索（阶段 3）：BM25 关键词 + 向量双路召回 → RRF 融合 → 重排精排。

设计要点（含金量所在）：
- BM25 用 jieba 分词 + 字符二元组兜底（中文子串也能召回）；
- 分字段 token 按素材缓存（index_cache），命中缓存零分词；
  过滤下推 SQL、只查轻量列，融合后仅为 top-N 候选取完整素材行；
- 字段权重随素材分布自适应：视频/音频占比高 → 转写匹配权重更高（领域由数据决定）；
- 向量召回在 embedding 可用时启用，与 BM25 用 RRF(60) 融合；
- 重排模型可用时对 top-N 精排，失败自动降级为 RRF 结果。
"""
from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy.orm import Session

from ..core.config import settings
from ..llm.client import client as llm_client
from ..models import Asset, Tag
from .bm25 import BM25, tokenize
from .index_cache import adaptive_weights, docs_for, searchable_text
from .vector_store import vector_store

logger = logging.getLogger(__name__)

RRF_K = 60
RERANK_CANDIDATES = 20

_VISUAL_KEYWORDS = (
    "色", "蓝", "红", "绿", "黄", "紫", "橙", "夜空", "天空", "雪", "灯光", "玻璃",
    "镜面", "方块", "剪影", "夜景", "晚霞", "像素", "阳光", "海面", "山", "楼", "光",
    "画面", "图", "条纹", "彩色",
)


def _is_visual_query(query: str) -> bool:
    """查询是否带视觉特征（颜色/形状/光影），决定是否启用图片级多模态向量。"""
    return any(k in query for k in _VISUAL_KEYWORDS)


def _rrf(score_lists: list[dict[int, float]], k: int = RRF_K) -> dict[int, float]:
    fused: Counter[int] = Counter()
    for scores in score_lists:
        if not scores:
            continue
        for rank, doc_id in enumerate(sorted(scores, key=lambda i: scores[i], reverse=True)):
            fused[doc_id] += 1.0 / (k + rank + 1)
    return dict(fused)


def search(
    db: Session,
    query: str,
    modality: str | None = None,
    tag: str | None = None,
    limit: int = 20,
    strategy: str = "full",
    owner: str | None = None,
) -> list[tuple[Asset, float]]:
    """strategy: bm25=仅关键词 / rrf=关键词+向量 / full=再加重排（默认）。"""
    query = (query or "").strip()
    if not query:
        return []

    # 1) 轻量候选集：只取 id/updated_at/modality，不拉正文大文本（过滤下推 SQL）
    q = db.query(Asset.id, Asset.updated_at, Asset.modality).filter(
        Asset.status == "ready", Asset.deleted_at.is_(None)
    )
    if owner:
        q = q.filter(Asset.owner == owner)
    if modality:
        q = q.filter(Asset.modality == modality)
    rows = q.all()
    if tag:
        tagged = {t[0] for t in db.query(Tag.asset_id).filter(Tag.name == tag).all()}
        rows = [r for r in rows if r.id in tagged]
    if not rows:
        return []

    # 2) BM25 文档：指纹 = updated_at + 标签集合，内容/标签变更自动失效
    tag_rows = (
        db.query(Tag.asset_id, Tag.id, Tag.name)
        .filter(Tag.asset_id.in_([r.id for r in rows]))
        .all()
    )
    tags_by_asset: dict[int, list[tuple[int, str]]] = {}
    for asset_id, tid, name in tag_rows:
        tags_by_asset.setdefault(asset_id, []).append((tid, name))
    fingerprints = {
        r.id: (r.updated_at, tuple(sorted(tags_by_asset.get(r.id, []))))
        for r in rows
    }
    field_tokens = docs_for(db, fingerprints)
    ids = [r.id for r in rows if r.id in field_tokens]
    if not ids:
        return []

    weights = adaptive_weights([r.modality for r in rows])
    docs: list[tuple[int, Counter]] = []
    for aid in ids:
        freq: Counter = Counter()
        for field, toks in field_tokens[aid].items():
            weight = weights.get(field)
            if not weight:
                continue
            for tok in toks:
                freq[tok] += weight
        docs.append((aid, freq))
    bm25 = BM25(docs)
    # 零分不参与 RRF（否则每个素材都会拿到 1/61 的保底分）
    bm25_scores = {k: v for k, v in bm25.score(tokenize(query)).items() if v > 0}

    # 3) 向量召回：文本向量（bge-m3）+ 图片向量（VL-Embedding，tri/full/gate 启用）
    score_lists: list[dict[int, float]] = [bm25_scores]
    if strategy in ("rrf", "tri", "gate", "full") and len(vector_store) > 0:
        try:
            vecs = llm_client.embed_texts([query])
            if vecs:
                score_lists.append(vector_store.search(vecs[0], settings.embedding_model, top_k=50))
        except Exception as e:
            logger.warning("文本向量检索失败，退回关键词: %s", e)
    # 门控：仅"视觉查询"启用图片级多模态向量（否则 VL 噪声会淹没语义查询）
    use_vl = strategy in ("tri", "full") or (strategy == "gate" and _is_visual_query(query))
    if use_vl:
        try:
            vecs = llm_client.embed_texts_vl([query])
            if vecs:
                score_lists.append(vector_store.search(vecs[0], settings.vl_embedding_model, top_k=50))
        except Exception as e:
            logger.warning("多模态向量检索失败（已降级）: %s", e)

    # 4) RRF 融合（两路或三路），只把 top-N 候选的完整素材行取出来
    fused = _rrf(score_lists)
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[: max(limit, RERANK_CANDIDATES)]
    if not ranked:
        return []
    allowed = {r.id for r in rows}
    top_ids = [i for i, _ in ranked]
    cand_q = db.query(Asset).filter(
        Asset.id.in_(top_ids), Asset.status == "ready", Asset.deleted_at.is_(None)
    )
    if owner:
        cand_q = cand_q.filter(Asset.owner == owner)
    asset_by_id = {a.id: a for a in cand_q}
    candidates = [(asset_by_id[i], s) for i, s in ranked if i in asset_by_id and i in allowed]

    # 5) 重排精排（失败自动降级）
    if strategy == "full" and len(candidates) >= 2:
        try:
            texts = [" ".join(v for v in searchable_text(a).values())[:500] for a, _ in candidates]
            rerank_scores = llm_client.rerank(query, texts)
            if rerank_scores:
                candidates = [(a, rerank_scores[i]) for i, (a, _) in enumerate(candidates)]
                candidates.sort(key=lambda x: x[1], reverse=True)
                return candidates[:limit]
        except Exception as e:
            logger.warning("重排失败（已降级为 RRF 结果）: %s", e)

    return [(a, round(s, 4)) for a, s in candidates[:limit]]
