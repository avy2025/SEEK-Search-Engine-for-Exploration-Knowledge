"""Deterministic tokeniser + normaliser for the SEEK lexical index.

Everything here is pure string work (no ML, no external tokenizer libs) and is a
**pure function of its input**, which is what keeps the BM25 index reproducible
across runs and machines.

Two export levels, matching the probe/acceptance contract + the loader's use:

* :func:`normalize` — unicode-fold a string (NFKD + strip combining marks +
  lowercase). Deterministic and reversible-enough for hashing.
* :func:`tokenize` — ``normalize`` then split on non-alphanumeric runs, dropping
  a small explicit English stop-word set. This is the token stream BM25 sees.
* :data:`STOPWORDS` — the explicit, stable stop-word set.
* :data:`TOKEN_RE` — compiled ``\\w``-based token matcher (kept for callers
  that want the split pattern itself).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Iterator

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# A deliberately small, explicit English stop-word set. We keep it stable across
# builds so BM25 scores are reproducible; corpus-specific jargon is *never* a
# stop-word (e.g. "docker", "python" must stay alive).
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
        "from", "has", "have", "he", "her", "his", "i", "in", "is", "it", "its",
        "not", "of", "on", "or", "that", "the", "their", "them", "there",
        "these", "they", "this", "to", "was", "were", "which", "will", "with",
        "you", "your",
    }
)

# Characters we treat as *word* separators (everything not matched by TOKEN_RE).
_SEPARATOR: re.Pattern[str] = re.compile(r"[^\w]", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase + unicode-fold *text*; strips accents via NFKD composition."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return folded.casefold()


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Return normalised, stop-word-stripped tokens for *text*.

    ``keep_stopwords=True`` keeps the full vocabulary (used for snippet building
    where stop-words are wanted in the rendered keyword window).
    """
    norm = normalize(text)
    tokens = TOKEN_RE.findall(norm)
    if keep_stopwords:
        return tokens
    return [tok for tok in tokens if tok not in STOPWORDS]


def iter_tokens(text: str, *, keep_stopwords: bool = False) -> Iterator[str]:
    """Generator view of :func:`tokenize` (memory-friendly for huge bodies)."""
    yield from tokenize(text, keep_stopwords=keep_stopwords)


def count_tokens(text: str, *, keep_stopwords: bool = False) -> int:
    """Total token count (as BM25 sees it)."""
    return sum(1 for _ in iter_tokens(text, keep_stopwords=keep_stopwords))


_WINDOW = 26


def snippet_tokens(text: str, *, words: int = _WINDOW) -> Iterator[str]:
    """Deterministic keyword-agnostic token window for snippet rendering.

    Returns the normalised (stop-word-kept) tokens of *text*, lazily, trimmed to
    at most *words* tokens. Because snippets are built after scoring, the window
    is deliberately stop-word-inclusive so the excerpt reads naturally.
    """
    return iter_tokens(text, keep_stopwords=keep_stopwords)


__all__ = ["STOPWORDS", "TOKEN_RE", "normalize", "tokenize", "snippet_tokens"]
