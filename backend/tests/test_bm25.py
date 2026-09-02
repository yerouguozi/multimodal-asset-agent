"""BM25 检索器单元测试。"""
from collections import Counter

from app.retrieval.bm25 import BM25, tokenize


def test_tokenize_chinese_bigram_fallback():
    toks = tokenize("城市夜景")
    assert "夜景" in toks  # 二元组兜底保证子串召回


def test_bm25_ranks_relevant_first():
    docs = [
        (1, Counter(tokenize("城市夜景 摩天大楼 灯光"))),
        (2, Counter(tokenize("产品海报 营销方案 促销"))),
    ]
    bm = BM25(docs)
    scores = bm.score(tokenize("夜景"))
    assert scores[1] > 0
    assert scores[1] > scores[2]


def test_bm25_empty_query():
    bm = BM25([(1, Counter(tokenize("abc"))), (2, Counter(tokenize("def")))])
    assert bm.score([]) == {1: 0.0, 2: 0.0}


def test_bm25_empty_docs():
    bm = BM25([])
    assert bm.score(["夜景"]) == {}
