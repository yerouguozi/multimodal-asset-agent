"""BM25（Okapi）关键词检索：jieba 中文分词 + 字符二元组兜底。

自己实现而不是用现成库的原因：
- 无额外依赖，逻辑透明，公式张口就来；
- 词频按字段权重放大，方便做"领域自适应加权"。
"""
from __future__ import annotations

import math
import re
from collections import Counter

import jieba

_K1 = 1.5
_B = 0.75
_PUNCT_RE = re.compile(r"[\s\W_]+")


def tokenize(text: str) -> list[str]:
    """jieba 分词 + 中文二元组兜底（保证子串级召回），返回去重保序 token 列表。"""
    text = (text or "").lower()
    tokens = [t for t in jieba.cut(text) if t.strip() and not _PUNCT_RE.fullmatch(t)]
    chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


class BM25:
    """Okapi BM25。docs 形如 [(doc_id, Counter{token: 加权词频})]。"""

    def __init__(self, docs: list[tuple[int, Counter]]) -> None:
        self.doc_ids = [d for d, _ in docs]
        self.freqs = [f for _, f in docs]
        self.doc_lens = [float(sum(f.values())) for f in self.freqs]
        self.n_docs = len(docs)
        self.avg_len = sum(self.doc_lens) / self.n_docs if self.n_docs else 0.0

        df: Counter[str] = Counter()
        for f in self.freqs:
            for t in f:
                df[t] += 1
        self.idf = {
            t: math.log(1.0 + (self.n_docs - n + 0.5) / (n + 0.5))
            for t, n in df.items()
        }

    def score(self, query_tokens: list[str]) -> dict[int, float]:
        scores = {doc_id: 0.0 for doc_id in self.doc_ids}
        if not self.n_docs:
            return scores
        terms = set(query_tokens)
        for doc_id, freq, dl in zip(self.doc_ids, self.freqs, self.doc_lens):
            denom_base = _K1 * (1 - _B + _B * dl / self.avg_len) if self.avg_len else _K1
            s = 0.0
            for t in terms:
                tf = freq.get(t, 0.0)
                if tf <= 0:
                    continue
                s += self.idf.get(t, 0.0) * (tf * (_K1 + 1)) / (tf + denom_base)
            scores[doc_id] = s
        return scores
