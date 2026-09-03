"""片段级检索：长文档按 chunk 召回，返回原文片段与出处（asset + seq）。

与资产级检索互补：资产级回答"哪个素材相关"；片段级回答"具体在哪一段说了什么"。
旧数据首次查询时自动按需补分块（懒回填），无需重跑流水线。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..core.config import settings
from ..llm.client import client as llm_client
from ..models import Asset, DocumentChunk
from ..pipeline.chunking import chunk_text
from .bm25 import BM25, tokenize

logger = logging.getLogger(__name__)

RERANK_CANDIDATES = 20


def ensure_chunks(db: Session, asset: Asset) -> list[DocumentChunk]:
    """返回资产的 chunk；老数据没有时按正文懒生成并落库。"""
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.asset_id == asset.id)
        .order_by(DocumentChunk.seq.asc())
        .all()
    )
    if rows:
        return rows
    texts = chunk_text(asset.text_content)
    rows = []
    for seq, text in enumerate(texts):
        c = DocumentChunk(asset_id=asset.id, seq=seq, text=text)
        db.add(c)
        rows.append(c)
    if texts:
        db.commit()
    return rows


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
    q = db.query(Asset).filter(Asset.status == "ready", Asset.modality == "document")
    if owner:
        q = q.filter(Asset.owner == owner)
    docs: list[tuple[int, object]] = []
    for asset in q.all():
        if not asset.text_content:
            continue
        for chunk in ensure_chunks(db, asset):
            docs.append((chunk.id, (asset, chunk)))

    if not docs:
        return []
    docs_tokens: list[tuple[int, dict]] = []
    for chunk_id, (asset, chunk) in docs:
        freq: dict[str, float] = {}
        for tok in tokenize(chunk.text):
            freq[tok] = freq.get(tok, 0.0) + 1.0
        for tok in tokenize(asset.name):
            freq[tok] = freq.get(tok, 0.0) + 1.5
        docs_tokens.append((chunk_id, freq))
    scores = BM25(docs_tokens).score(tokenize(query))
    ranked = sorted(((i, s) for i, s in scores.items() if s > 0), key=lambda x: x[1], reverse=True)
    if not ranked:
        return []
    ranked = ranked[: max(limit, RERANK_CANDIDATES)]
    by_id = {chunk_id: (asset, chunk) for chunk_id, (asset, chunk) in docs}
    candidates = [(by_id[i][0], by_id[i][1], s) for i, s in ranked if i in by_id]

    if rerank and len(candidates) >= 2:
        try:
            texts = [f"{a.name}\n{c.text}"[:600] for a, c, _ in candidates]
            scores = llm_client.rerank(query, texts)
            if scores:
                candidates = [
                    (a, c, scores[i])
                    for i, (a, c, _) in enumerate(candidates)
                    if i < len(scores)
                ]
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
                "score": round(float(score), 4),
            }
        )
    return out
