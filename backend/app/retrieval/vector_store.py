"""本地向量存储（numpy + npz 落盘）。

设计：VectorStore 是抽象能力，LocalVectorStore 是当前实现；
阶段 3 检索升级时可无缝替换为 Milvus（同接口）。
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..core.config import settings

logger = logging.getLogger(__name__)


class LocalVectorStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._vectors: dict[int, np.ndarray] = {}
        self._load()

    def __len__(self) -> int:
        return len(self._vectors)

    def add(self, asset_id: int, vector: list[float], model: str) -> None:
        self._vectors[asset_id] = np.asarray(vector, dtype=np.float32)
        self._save()

    def delete(self, asset_id: int) -> None:
        if asset_id in self._vectors:
            del self._vectors[asset_id]
            self._save()

    def clear(self) -> None:
        self._vectors.clear()
        self._save()

    def search(self, query_vec: list[float] | None, top_k: int = 20) -> dict[int, float]:
        """余弦相似度检索，返回 {asset_id: sim}（仅保留 >0 的命中）。"""
        if not self._vectors or query_vec is None:
            return {}
        ids = list(self._vectors.keys())
        mat = np.stack(list(self._vectors.values()))
        q = np.asarray(query_vec, dtype=np.float32)
        qn = q / (np.linalg.norm(q) + 1e-9)
        matn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
        sims = matn @ qn
        order = np.argsort(-sims)[:top_k]
        return {ids[i]: float(sims[i]) for i in order if sims[i] > 0}

    # ---------- 持久化 ----------

    def _save(self) -> None:
        if not self._vectors:
            self.path.unlink(missing_ok=True)
            return
        ids = np.array(list(self._vectors.keys()), dtype=np.int64)
        mat = np.stack(list(self._vectors.values()))
        tmp = self.path.with_suffix(".npz.tmp")
        np.savez(tmp, ids=ids, mat=mat)
        tmp.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with np.load(self.path) as d:
                for aid, vec in zip(d["ids"], d["mat"]):
                    self._vectors[int(aid)] = vec.astype(np.float32)
        except Exception as e:
            logger.warning("向量库加载失败（按空库启动）: %s", e)


vector_store = LocalVectorStore(settings.vector_store_file)
