"""检索指标单元测试（口径正确性）。"""
from app.retrieval.metrics import mrr, ndcg_at_k, recall_at_k


def test_recall_at_k():
    assert recall_at_k({1, 2}, [3, 1, 4, 2], 3) == 0.5
    assert recall_at_k({1, 2}, [3, 1, 4, 2], 4) == 1.0
    assert recall_at_k({1}, [], 5) == 0.0
    assert recall_at_k(set(), [1], 5) == 0.0


def test_mrr():
    assert mrr({1, 2}, [3, 1, 4]) == 0.5
    assert mrr({1}, [1, 2]) == 1.0
    assert mrr({1}, [2, 3]) == 0.0


def test_ndcg_perfect_ranking_is_one():
    assert ndcg_at_k({1, 2, 3}, [1, 2, 3], 3) == 1.0


def test_ndcg_bad_ranking_lower():
    perfect = ndcg_at_k({1, 2, 3}, [1, 2, 3], 3)
    worse = ndcg_at_k({1, 2, 3}, [1, 99, 2], 3)  # 不相关文档占了第2位
    assert worse < perfect
    assert ndcg_at_k({1, 2, 3}, [], 3) == 0.0
