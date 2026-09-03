"""chunk 级向量库：与素材向量库同构，可按 VECTOR_BACKEND 切换本地/Milvus。

Milvus 用独立集合命名空间（mma_chunk_*）避免与素材主键冲突；
连接失败自动降级本地 npz。
"""
from __future__ import annotations

import logging

from ..core.config import settings
from .vector_store import LocalVectorStore

logger = logging.getLogger(__name__)


def create_chunk_vector_store():
    if settings.vector_backend == "milvus":
        try:
            from .milvus_store import MilvusVectorStore

            return MilvusVectorStore(settings.milvus_uri, collection_prefix="mma_chunk_")
        except Exception as e:
            logger.warning("Chunk Milvus 不可用，降级本地片段向量库: %s", e)
    return LocalVectorStore(settings.chunk_vector_file)


chunk_vector_store = create_chunk_vector_store()
