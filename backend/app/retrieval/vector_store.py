"""本地向量存储（numpy + npz 落盘），按模型分空间。

多模态二期：图片有 VL-Embedding（4096 维）、文本有 bge-m3（1024 维），
不同模型向量维度不同，因此按 model 分空间存储与检索。
VectorStore 仍是抽象能力，后续可换 Milvus（同接口）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np

from ..core.config import settings

logger = logging.getLogger(__name__)


def _slug(model: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", model).strip("_")


class LocalVectorStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._spaces: dict[str, dict[int, np.ndarray]] = {}
        # 归一化矩阵缓存：add/delete/clear 时失效，查询免重复归一化
        self._norm_cache: dict[str, tuple[list[int], "np.ndarray"]] = {}
        self._load()

    def __len__(self) -> int:
        return sum(len(s) for s in self._spaces.values())

    def models(self) -> list[str]:
        return list(self._spaces.keys())

    def keys(self, model: str) -> set[int]:
        return set(self._spaces.get(model, {}).keys())

    def add(self, asset_id: int, vector: list[float], model: str) -> None:
        self._spaces.setdefault(model, {})[asset_id] = np.asarray(vector, dtype=np.float32)
        self._norm_cache.pop(model, None)
        self._save(model)

    def delete(self, asset_id: int) -> None:
        self.delete_ids([asset_id])

    def delete_ids(self, ids: list[int]) -> None:
        """批量删除（purge 素材时顺带清理它的全部 chunk 向量）。"""
        if not ids:
            return
        id_set = set(ids)
        for space in self._spaces.values():
            for i in id_set:
                space.pop(i, None)
        self._norm_cache.clear()
        self._save_all()

    def clear(self) -> None:
        self._spaces.clear()
        self._norm_cache.clear()
        for f in self.path.parent.glob(f"{self.path.stem}_*.npz"):
            f.unlink(missing_ok=True)

    def search(self, query_vec: list[float] | None, model: str, top_k: int = 20) -> dict[int, float]:
        """指定模型空间内做余弦相似度检索，返回 {asset_id: sim}（仅保留 >0）。"""
        space = self._spaces.get(model, {})
        if not space or query_vec is None:
            return {}
        cached = self._norm_cache.get(model)
        if cached is None:
            ids = list(space.keys())
            mat = np.stack(list(space.values()))
            matn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
            cached = (ids, matn)
            self._norm_cache[model] = cached
        ids, matn = cached
        q = np.asarray(query_vec, dtype=np.float32)
        qn = q / (np.linalg.norm(q) + 1e-9)
        sims = matn @ qn
        order = np.argsort(-sims)[:top_k]
        return {ids[i]: float(sims[i]) for i in order if sims[i] > 0}

    # ---------- 持久化 ----------

    def _file_for(self, model: str) -> Path:
        return self.path.parent / f"{self.path.stem}_{_slug(model)}.npz"

    def _save(self, model: str) -> None:
        space = self._spaces.get(model, {})
        f = self._file_for(model)
        if not space:
            f.unlink(missing_ok=True)
            return
        ids = np.array(list(space.keys()), dtype=np.int64)
        mat = np.stack(list(space.values()))
        # np.savez 会对不以 .npz 结尾的路径自动追加 .npz，文件名必须以 .npz 结尾
        tmp = f.with_name(f"{f.stem}.tmp.npz")
        np.savez(tmp, ids=ids, mat=mat, model=np.array([model]))
        tmp.replace(f)

    def _save_all(self) -> None:
        for model in list(self._spaces.keys()):
            self._save(model)

    def _load(self) -> None:
        for f in self.path.parent.glob(f"{self.path.stem}_*.npz"):
            try:
                with np.load(f) as d:
                    model = str(d["model"][0]) if "model" in d else f.stem[len(self.path.stem) + 1 :]
                    self._spaces[model] = {
                        int(aid): vec.astype(np.float32)
                        for aid, vec in zip(d["ids"], d["mat"])
                    }
            except Exception as e:
                logger.warning("向量库加载失败（文件 %s）: %s", f.name, e)


def create_vector_store():
    """按配置选择后端：milvus（连接失败自动降级 local）。"""
    if settings.vector_backend == "milvus":
        try:
            from .milvus_store import MilvusVectorStore

            return MilvusVectorStore(settings.milvus_uri)
        except Exception as e:
            logger.warning("Milvus 不可用，降级本地向量库: %s", e)
    return LocalVectorStore(settings.vector_store_file)


vector_store = create_vector_store()
