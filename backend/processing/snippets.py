"""Keyword-aware snippet building — SEEK Phase 2 excerpt layer.

Bare-bones excerpt chosen to be (a) deterministic, (b) keyword-aware so the
snippet visibly reflects the query, and (c) cheap. It never calls anything
networked; output is plain text (Markdown source may keep inline code ticks,
which is fine for a first pass).

API
---
* :func:`make_snippet` — build a keyword-aware excerpt for one hit.
* :func:`_leading_window` — internal helper (exposed for tests).

Both accept token streams already produced by
:func:`backend.processing.tokenizer.tokenize` so snippet code never
re-tokenises the whole corpus.
"""
from __future__ import annotations

from typing import Iterable

from backend.processing.tokenizer import STOPWORDS, TOKEN_RE, normalize, tokenize

# How many normalised words a snippet shows by default.
SNIPPET_WORDS = 26


def make_snippet(
    content: str,
    query_tokens: Iterable[str],
    *,
    words: int = SNIPPET_WORDS,
    keep_stopwords: bool = True,
) -> str:
    """Return a deterministic keyword-aware excerpt of *content*.

    Strategy: pick the first paragraph containing a query token, then emit a
    window of up to *words* tokens centred on the first matching token. If no
    paragraph matches, the leading tokens of *content* are used. Degenerates to
    ``""`` only when *content* is empty.
    """
    if not content:
        return ""
    qset = {t for t in query_tokens if t}
    if not qset:
        return _leading_window(content, words)
    paragraphs = _split_paragraphs(content)
    for para in paragraphs:
        tokens = tokenize(para, keep_stopwords=keep_stopwords)
        if any(t in qset for t in tokens):
            return _window_around(tokens, qset, words=words)
    return _leading_window(content, words)


def _split_paragraphs(content: str) -> list[str]:
    return [p.strip() for p in content.splitlines() if p.strip()]


def _window_around(tokens: list[str], qset: set[str], *, words: int) -> str:
    anchor = next((i for i, t in enumerate(tokens) if t in qset), 0)
    half = max(1, words // 2)
    start = max(0, anchor - half)
    end = min(len(tokens), anchor + half + 1)
    return " ".join(tokens[start:end]) or ""


def _leading_window(content: str, words: int) -> str:
    return " ".join(tokenize(content, keep_stopwords=True)[:words])


build_snippet = make_snippet
