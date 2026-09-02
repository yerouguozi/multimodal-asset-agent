"""Milvus 向量库（可选后端）。

接口与 LocalVectorStore 对齐（add / search / delete / clear / models / __len__）。
需要 pymilvus 与运行中的 Milvus；连接失败时上层自动降级到本地库。
注意：本环境无 Milvus 服务，此实现为接口就绪 + 文档说明，未做端到端实测。
"""
from __future__ import annotations

import re


class MilvusVectorStore:
    def __init__(self, uri: str, token: str = "", collection_prefix: str = "mma_"):
        from pymilvus import connections

        self.uri = uri
        self.token = token
        self.prefix = collection_prefix
        connections.connect(alias="mma", uri=uri, token=token)
        self._collections: dict[str, object] = {}

    @staticmethod
    def _slug(model: str) -> str:
        return re.sub(r"[^0-9A-Za-z]+", "_", model).strip("_")

    def _collection(self, model: str, dim: int | None = None):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

        name = self.prefix + self._slug(model)
        if name in self._collections:
            return self._collections[name]
        if utility.has_collection(name, using="mma"):
            col = Collection(name, using="mma")
        else:
            if dim is None:
                raise ValueError("dim 未知，无法建集合")
            fields = [
                FieldSchema("asset_id", DataType.INT64, is_primary=True),
                FieldSchema("vector", DataType.FLOAT_VECTOR, dim=dim),
            ]
            col = Collection(name, schema=CollectionSchema(fields, description="mma assets"), using="mma")
            col.create_index("vector", {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}})
        self._collections[name] = col
        return col

    def __len__(self) -> int:
        total = 0
        for col in self._collections.values():
            total += col.num_entities
        return total

    def models(self) -> list[str]:
        from pymilvus import utility

        names = utility.list_collections(using="mma")
        return [n[len(self.prefix):] for n in names if n.startswith(self.prefix)]

    def add(self, asset_id: int, vector: list[float], model: str) -> None:
        col = self._collection(model, dim=len(vector))
        col.insert([[asset_id], [list(vector)]])
        col.flush()

    def search(self, query_vec: list[float] | None, model: str, top_k: int = 20) -> dict[int, float]:
        if query_vec is None:
            return {}
        col = self._collection(model, dim=len(query_vec))
        if col.num_entities == 0:
            return {}
        res = col.search(
            data=[list(query_vec)],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 16}},
            limit=top_k,
            output_fields=["asset_id"],
        )
        return {int(h.entity.get("asset_id")): float(h.distance) for h in res[0]}

    def delete(self, asset_id: int) -> None:
        from pymilvus import Collection, utility

        for name in utility.list_collections(using="mma"):
            if not name.startswith(self.prefix):
                continue
            col = Collection(name, using="mma")
            col.delete(f"asset_id == {asset_id}")
            col.flush()

    def clear(self) -> None:
        from pymilvus import utility

        for name in utility.list_collections(using="mma"):
            if name.startswith(self.prefix):
                utility.drop_collection(name, using="mma")
        self._collections.clear()
