"""Query-side normalisation and token weighting for the BM25 search MVP.

A query is deliberately processed with the *same* token/normalisation rules as
the corpus (:mod:`backend.processing.tokenizer`) so that a user typing
``"Docker  Compose"`` or ``"dcoker"`` queries the same token space the index was
built with — no transformations only applied on one side.

The output model is a *weighted* query: each unique token keeps its raw
``weight`` (1.0 by default; higher when repeated in the query). Weights are
consumed by :class:`backend.search.engine` when it folds multi-term queries
into BM25 scores.
"""
from __future__ import annotations

from typing import Iterable

from backend.processing.tokenizer import normalize, tokenize

WILDCARD = "*"
MAX_QUERY_TOKENS = 64


class WeightedQueryToken:
    """A single query token paired with its search weight."""

    __slots__ = ("token", "weight")

    def __init__(self, token: str, weight: float = 1.0) -> None:
        self.token = token
        self.weight = float(weight)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"WeightedQueryToken(token={self.token!r}, weight={self.weight})"


class QueryProcessor:
    """Normalise + tokenise user queries and yield weighted token streams."""

    @staticmethod
    def normalize_query(raw_query: str) -> str:
        """Strip leading/trailing whitespace and fold the whole string."""
        return normalize(raw_query.strip())

    def process(self, raw_query: str) -> list[WeightedQueryToken]:
        """Tokenise *raw_query* and return per-token weights (query-side rules).

        Wildcard ``*`` usages are dropped here and handled higher up by the
        engine (prefix expansion); a query made only of separators yields "". 
        """
        folded = self.normalize_query(raw_query)
        if not folded:
            return []
        tokens: list[str] = []
        for chunk in folded.split():
            chunk_tokens = tokenize(chunk, keep_stopwords=True)
            tokens.extend(chunk_tokens)
        if not tokens:
            return []

        # Deterministic ordering: first-seen order, then stable by lexicographic
        # tie-break so weighted output is reproducible across Python versions.
        seen: dict[str, float] = {}
        for tok in tokens:
            seen[tok] = seen.get(tok, 0.0) + 1.0
        ordered = sorted(set(seen), key=lambda t: (tokens.index(t), t))
        return [WeightedQueryToken(tok, seen[tok]) for tok in ordered]


def token_stream(raw_query: str) -> Iterable[str]:
    """Yield normalised tokens of *raw_query* (no weights; index-side view)."""
    folded = QueryProcessor.normalize_query(raw_query)
    if not folded:
        return ()
    return tokenize(folded, keep_stopwords=True)
