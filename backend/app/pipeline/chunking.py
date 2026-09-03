"""段落感知长文档分块：优先按空行切段打包，超长段落再按字符窗口 + 重叠切。"""
from __future__ import annotations

import re

MAX_CHUNK_CHARS = 420
OVERLAP_CHARS = 60


def _slice_long(paragraph: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    step = max(1, max_chars - overlap)
    return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), step)]


def chunk_text(
    text: str | None,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if buf:
            chunks.append("\n".join(buf))
        buf = []
        buf_len = 0

    for p in paragraphs:
        if len(p) > max_chars:
            flush()
            chunks.extend(_slice_long(p, max_chars, overlap))
            continue
        if buf and buf_len + len(p) + 1 > max_chars:
            flush()
        buf.append(p)
        buf_len += len(p) + 1
    flush()
    return chunks
