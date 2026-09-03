"""chunk 级向量库：复用 LocalVectorStore（npz 落盘），键为 DocumentChunk.id。"""
from __future__ import annotations

from ..core.config import settings
from .vector_store import LocalVectorStore

chunk_vector_store = LocalVectorStore(settings.chunk_vector_file)
