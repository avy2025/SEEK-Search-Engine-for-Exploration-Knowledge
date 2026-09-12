"""BM25 ranked retrieval over the in-memory token index (Phase 2).

Wraps ``rank_bm25.BM25Okapi`` into a compact, deterministic service object the
SEEK engine can use without exposing library details to the API layer.

Scoring notes
-------------
* ``k1`` / ``b`` come from :data:`backend.config.settings` (Phase 2 defaults
  1.5 / 0.75, the classic Okapi tuning).
* Documents with zero content tokens never enter the index; terms absent from
  the corpus get score 0.0.
* ``get_scores`` returns a flat ``list[float]`` aligned to ``self.documents``,
  which lets upper layers rank and then slice by ``limit`` without ever touching
  the DB per request.
"""
from __future__ import annotations

import logging
from typing import Iterable

from rank_bm25 import BM25Okapi

from backend.config import settings
from backend.processing.models import ProcessedDocument
from backend.processing.tokenizer import normalize, tokenize

logger = logging.getLogger("seek.search.bm25")


class Bm25Index:
    """A ready-to-query Okapi-BM25 index over the loaded corpus.

    The index is **built once** at startup (inside the FastAPI lifespan) and
    reused for every ``/api/search`` request — it is never rebuilt per query and
    never re-read from disk on request.
    """

    def __init__(
        self,
        documents: Iterable[ProcessedDocument],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ) -> None:
        self._documents: list[ProcessedDocument] = list(documents)
        self._titles: list[str] = [d.title for d in self._documents]
        self._token_lists: list[list[str]] = [
            list(d.tokens) for d in self._documents if d.tokens
        ]
        # The BM25Okapi reference implementation needs the raw token lists.
        self._corpus_tokens: list[list[str]] = self._token_lists
        self._bm25 = (
            BM25Okapi(self._corpus_tokens, k1=k1, b=b, epsilon=epsilon)
            if self._corpus_tokens
            else None
        )
        self._k1 = k1
        self._b = b
        self._lengths = [len(toks) for toks in self._corpus_tokens]
        self._avgdl = (
            float(sum(self._lengths)) / len(self._corpus_tokens)
            if self._corpus_tokens
            else 0.0
        )
        self._total_corpus_tokens = sum(self._lengths)

    # -- informational surface -------------------------------------------------
    @property
    def document_count(self) -> int:
        return len(self._documents)

    @property
    def vocabulary_size(self) -> int:
        """Number of distinct terms known to the index (stop-word-stripped)."""
        if self._bm25 is None:
            return 0
        return len(self._bm25.doc_freqs)

    @property
    def stats(self) -> dict[str, object]:
        return {
            "documents": self.document_count,
            "corpus_tokens": self._total_corpus_tokens,
            "average_document_length": round(self._avgdl, 3),
            "vocabulary": self.vocabulary_size,
            "k1": self._k1,
            "b": self._b,
        }

    _EMPTY_SCORES: list[float] = []

    def score(self, query_tokens: Iterable[str]) -> list[float]:
        """Return per-document BM25 scores for *query_tokens* (aligned to docs).

        The returned list is in the same order as ``self.documents``; documents
        whose tokens are empty map to score 0.0.
        """
        qt = [t for t in query_tokens if t]
        if not qt or not self._corpus_tokens or self._bm25 is None:
            return [0.0 for _ in self._documents]
        try:
            scores = self._bm25.get_scores(qt)
        except ValueError as exc:  # pragma: no cover - defensive
            logger.warning("BM25 scoring problem: %s", exc)
            scores = [0.0] * len(self._documents)
        # Guard against length mismatch (should never happen, kept cheap).
        if len(scores) != len(self._documents):
            scores = scores[: len(self._documents)] + [0.0] * max(
                0, len(self._documents) - len(scores)
            )
        return scores

    # -- documents ------------------------------------------------------------
    @property
    def documents(self) -> list[ProcessedDocument]:
        return self._documents

    def document(self, index: int) -> ProcessedDocument | None:
        """Return the *index*-th processed document, or ``None`` if out of range."""
        try:
            return self._documents[index]
        except IndexError:
            return None

    def term_frequency_profile(self) -> dict[str, int]:
        """Total term counts across the whole corpus (flat dict, for profiling)."""
        counts: dict[str, int] = {}
        for toks in self._corpus_tokens:
            for tok in toks:
                counts[tok] = counts.get(tok, 0) + 1
        return counts


# Phase 2 probe/pipeline spelling: expose the index under both the descriptive
# ``Bm25Index`` name and the terse ``Bm25`` alias used by ``backend.pipeline``
# and the Phase 2 acceptance probe.
Bm25 = Bm25Index

__all__ = ["BM25", "Bm25", "Bm25Index"]
