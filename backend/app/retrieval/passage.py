"""片段级检索：文档段落与音视频时间片的统一 chunk 检索。

BM25 + bge-m3 向量 RRF 融合 → bge-reranker 精排；输出原文与出处
(asset + seq，时间片附带 start/end)。旧数据首次查询自动懒回填。
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ..core.config import settings
from ..llm.client import client as llm_client
from ..models import Asset, DocumentChunk
from ..pipeline.chunking import chunk_text
from .bm25 import BM25, tokenize
from .chunk_vector import chunk_vector_store
from .index_cache import chunk_tokens

logger = logging.getLogger(__name__)

RRF_K = 60
RERANK_CANDIDATES = 20


def ensure_chunks(db: Session, asset: Asset) -> list[DocumentChunk]:
    """返回资产的 chunk；老数据没有时按正文/转写时间片懒生成并落库。"""
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.asset_id == asset.id)
        .order_by(DocumentChunk.seq.asc())
        .all()
    )
    if rows:
        return rows
    rows = []
    items: list[dict] = []
    if asset.modality == "document":
        items = [{"text": t, "start": None, "end": None} for t in chunk_text(asset.text_content)]
    else:
        try:
            segs = json.loads(asset.transcript_segments or "[]")
        except Exception:
            segs = []
        items = [
            {"text": (s.get("text") or "")[:1000], "start": s.get("start"), "end": s.get("end")}
            for s in segs
            if s.get("text")
        ]
    for seq, item in enumerate(items):
        c = DocumentChunk(
            asset_id=asset.id,
            modality=asset.modality,
            seq=seq,
            text=item["text"],
            start=item.get("start"),
            end=item.get("end"),
        )
        db.add(c)
        rows.append(c)
    if items:
        db.commit()
    return rows


def _ensure_chunk_vectors(chunks: list[DocumentChunk]) -> None:
    model = settings.embedding_model
    existing = chunk_vector_store.keys(model)
    missing = [c for c in chunks if c.id not in existing]
    if not missing:
        return
    try:
        # 分批嵌入：chunk 多时单批超限不会拖垮整批
        vecs = llm_client.embed_texts_batched([c.text for c in missing])
        if vecs:
            for c, v in zip(missing, vecs):
                chunk_vector_store.add(c.id, v, model)
    except Exception as e:
        logger.warning("片段向量懒回填失败（降级 BM25）: %s", e)


def _rrf(score_lists: list[dict[int, float]]) -> dict[int, float]:
    fused: dict[int, float] = {}
    for scores in score_lists:
        if not scores:
            continue
        for rank, doc_id in enumerate(sorted(scores, key=lambda i: scores[i], reverse=True)):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return fused


def search_passages(
    db: Session,
    query: str,
    owner: str | None = None,
    limit: int = 8,
    rerank: bool = True,
) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    q = db.query(Asset.id, Asset.name, Asset.modality).filter(
        Asset.status == "ready",
        Asset.modality.in_(["document", "audio", "video"]),
        Asset.deleted_at.is_(None),
    )
    if owner:
        q = q.filter(Asset.owner == owner)
    light = q.all()
    if not light:
        return []
    by_id = {a.id: a for a in light}
    asset_ids = list(by_id)

    # 已有 chunk 的一次查出（替代逐素材 N+1 查询）；
    # 只有缺 chunk 的旧数据才加载整行做懒回填，避免每次查询全量拉正文大文本
    have = {
        row[0]
        for row in db.query(DocumentChunk.asset_id)
        .filter(DocumentChunk.asset_id.in_(asset_ids))
        .distinct()
        .all()
    }
    need_backfill = [i for i in asset_ids if i not in have]
    if need_backfill:
        for asset in db.query(Asset).filter(Asset.id.in_(need_backfill)).all():
            ensure_chunks(db, asset)
    chunk_rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.asset_id.in_(asset_ids))
        .order_by(DocumentChunk.seq.asc())
        .all()
    )
    pairs = []
    for chunk in chunk_rows:
        light_asset = by_id.get(chunk.asset_id)
        if light_asset is not None:
            pairs.append((light_asset, chunk))
    if not pairs:
        return []

    _ensure_chunk_vectors([c for _, c in pairs])
    chunk_ids = {c.id for _, c in pairs}
    name_toks = {aid: tokenize(a.name) for aid, a in by_id.items()}
    docs_tokens: list[tuple[int, dict[str, float]]] = []
    for asset, chunk in pairs:
        freq: dict[str, float] = {t: 1.0 for t in chunk_tokens(chunk)}
        for tok in name_toks[chunk.asset_id]:
            freq[tok] = freq.get(tok, 0.0) + 1.5
        docs_tokens.append((chunk.id, freq))

    score_lists: list[dict[int, float]] = []
    bm25_scores = BM25(docs_tokens).score(tokenize(query))
    bm25_positive = {k: v for k, v in bm25_scores.items() if v > 0 and k in chunk_ids}
    if bm25_positive:
        score_lists.append(bm25_positive)

    try:
        qvec = llm_client.embed_texts([query])
        if qvec:
            vec_hits = chunk_vector_store.search(qvec[0], settings.embedding_model, top_k=80)
            vec_owned = {k: v for k, v in vec_hits.items() if k in chunk_ids}
            if vec_owned:
                score_lists.append(vec_owned)
    except Exception as e:
        logger.warning("片段向量检索失败（降级 BM25）: %s", e)

    if not score_lists:
        return []
    fused = _rrf(score_lists)
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[
        : max(limit, RERANK_CANDIDATES)
    ]
    by_id = {c.id: (a, c) for a, c in pairs}
    candidates = [(by_id[i][0], by_id[i][1], s) for i, s in ranked if i in by_id]

    if rerank and len(candidates) >= 2:
        try:
            texts = [f"{a.name}\n{c.text}"[:600] for a, c, _ in candidates]
            scores = llm_client.rerank(query, texts)
            if scores:
                candidates = [(a, c, scores[i]) for i, (a, c, _) in enumerate(candidates) if i < len(scores)]
                candidates.sort(key=lambda x: x[2], reverse=True)
        except Exception as e:
            logger.warning("片段重排失败（已降级）: %s", e)

    out = []
    for asset, chunk, score in candidates[:limit]:
        out.append(
            {
                "asset_id": asset.id,
                "chunk_id": chunk.id,
                "seq": chunk.seq,
                "name": asset.name,
                "modality": asset.modality,
                "text": chunk.text,
                "start": chunk.start,
                "end": chunk.end,
                "score": round(float(score), 4),
            }
        )
    return out
