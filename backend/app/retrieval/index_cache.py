"""BM25 文档缓存：按素材缓存分字段 token 集合，命中时检索零分词。

jieba 分词是检索的 CPU 大头（全素材 × 全字段），每次查询重做一遍太浪费。
失效依据是指纹 (updated_at, 标签集合)：任何内容或标签变更都会改变指纹，
写路径不需要埋失效点。检索在 FastAPI 线程池里并发执行，用锁保护重建。

chunk 级缓存以 chunk_id 为键：chunk 行只增删不改（重新入库生成新 id），无需失效。
"""
from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from ..models import Asset, DocumentChunk
from .bm25 import tokenize

FIELD_WEIGHTS: dict[str, float] = {
    "name": 2.0,
    "description": 1.2,
    "ocr": 0.8,
    "transcript": 1.0,
    "text_content": 1.0,
    "tags": 1.0,
}

# asset_id -> (指纹, {字段: token 集合})；加权在查询时按当次的自适应权重应用
_field_cache: dict[int, tuple[tuple, dict[str, frozenset[str]]]] = {}
# (chunk_id, chunk_text) -> token 集合；键带文本是因为 SQLite 会复用被删 chunk 的 id
_chunk_cache: dict[tuple[int, str], frozenset[str]] = {}
_lock = threading.Lock()


def searchable_text(asset: Asset) -> dict[str, str]:
    return {
        "name": asset.name,
        "description": asset.description or "",
        "ocr": asset.ocr_text or "",
        "transcript": asset.transcript or "",
        "text_content": asset.text_content or "",
        "tags": " ".join(t.name for t in asset.tags),
    }


def adaptive_weights(modalities: list[str]) -> dict[str, float]:
    """字段权重随素材分布自适应：视频/音频占比高 → 转写匹配权重更高。"""
    n = len(modalities) or 1
    video_share = modalities.count("video") / n
    audio_share = modalities.count("audio") / n
    weights = dict(FIELD_WEIGHTS)
    weights["transcript"] = round(1.0 + 0.5 * video_share + 0.3 * audio_share, 3)
    return weights


def _fingerprint(asset: Asset) -> tuple:
    return (asset.updated_at, tuple(sorted((t.id, t.name) for t in asset.tags)))


def docs_for(
    db: Session, wanted: dict[int, tuple]
) -> dict[int, dict[str, frozenset[str]]]:
    """返回 {asset_id: {字段: token 集合}}；指纹变化或未缓存的素材重新加载并分词。

    wanted 形如 {asset_id: (updated_at, 标签指纹)}，由调用方用轻量查询（不拉正文）算出。
    已被删除的素材在 wanted 里查不到行，结果中自然缺失，调用方跳过即可。
    """
    out: dict[int, dict[str, frozenset[str]]] = {}
    missing: list[int] = []
    with _lock:
        for aid, fp in wanted.items():
            entry = _field_cache.get(aid)
            if entry is not None and entry[0] == fp:
                out[aid] = entry[1]
            else:
                missing.append(aid)
    if missing:
        built: dict[int, tuple[tuple, dict[str, frozenset[str]]]] = {}
        for a in db.query(Asset).filter(Asset.id.in_(missing)).all():
            built[a.id] = (
                _fingerprint(a),
                {
                    field: frozenset(tokenize(text))
                    for field, text in searchable_text(a).items()
                },
            )
        with _lock:
            _field_cache.update(built)
        out.update({aid: fields for aid, (_, fields) in built.items()})
    return out


def chunk_tokens(chunk: DocumentChunk) -> frozenset[str]:
    """chunk 文本的 token 集合（缓存）。

    键带文本本身：SQLite 的整数主键删除后会复用 rowid，素材重新入库时
    新 chunk 可能拿到旧 id，仅按 id 缓存会把旧 token 串给新文本。
    """
    key = (chunk.id, chunk.text)
    cached = _chunk_cache.get(key)
    if cached is None:
        cached = frozenset(tokenize(chunk.text))
        _chunk_cache[key] = cached
    return cached


def cache_size() -> dict[str, int]:
    """缓存规模（诊断用）。"""
    return {"assets": len(_field_cache), "chunks": len(_chunk_cache)}
