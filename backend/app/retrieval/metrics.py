"""检索质量指标：Recall@k / MRR / NDCG@k。

指标口径（面试可讲）：
- Recall@k：前 k 个结果中命中相关文档的比例；
- MRR：第一个相关文档的倒数排名，测"最快找到"能力；
- NDCG@k：按位置折扣的累积增益归一化，测"排序质量"。
"""
from __future__ import annotations

import math


def recall_at_k(relevant: set[int], ranked: list[int], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for doc_id in ranked[:k] if doc_id in relevant)
    return hits / len(relevant)


def mrr(relevant: set[int], ranked: list[int]) -> float:
    for i, doc_id in enumerate(ranked):
        if doc_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(relevant: set[int], ranked: list[int], k: int) -> float:
    def dcg(rels: list[float]) -> float:
        return sum(r / math.log2(i + 2) for i, r in enumerate(rels))

    ranked_rel = [1.0 if d in relevant else 0.0 for d in ranked[:k]]
    ideal = [1.0] * min(k, len(relevant))
    idcg = dcg(ideal)
    if idcg <= 0:
        return 0.0
    return dcg(ranked_rel) / idcg
