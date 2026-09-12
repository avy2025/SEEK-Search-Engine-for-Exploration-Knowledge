"""Query-time search orchestration — the single public Phase 2 API entry point.

``SearchEngine`` is the object ``backend.pipeline`` hands to the FastAPI layer;
the API only ever sees this surface and the wire models in
:mod:`backend.search.models`. It deliberately:

* stays **stateless** between requests (no per-request caches),
* works entirely in-memory (BM25 index built at startup from the corpus), and
* never touches the database — persistence is an orthogonal best-effort concern
  owned by ``backend.pipeline``/``backend.db.repository_factory``.

Runtime contract (verified against this tree):

* index is built via :class:`~backend.search.bm25.Bm25Index`, constructed with
  the document list (k1/b as Okapi defaults 1.5/0.75),
* queries are processed with :class:`~backend.search.query.QueryProcessor`,
* hits come back as frozen :class:`SearchResult` wire items.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Sequence

from backend.processing.models import ProcessedDocument
from backend.processing.snippets import build_snippet
from backend.search.bm25 import Bm25Index
from backend.search.models import SearchQuery, SearchResponse, SearchResult
from backend.search.query import QueryProcessor

logger = logging.getLogger("seek.search.engine")


class SearchEngine:
    """Ranked search over the SEEK Phase 2 BM25 index.

    Owns one :class:`~backend.search.bm25.Bm25Index` (built from the corpus) and
    a :class:`~backend.search.query.QueryProcessor`; ``search`` scores the whole
    index, ranks by descending score, trims to ``limit`` and renders each hit's
    keyword-aware snippet from its content + matched query terms.
    """

    def __init__(
        self,
        documents: Iterable[ProcessedDocument] = (),
        *,
        k1: float = 1.5,
        b: float = 0.75,
        default_limit: int = 10,
        max_limit: int = 50,
    ) -> None:
        self._bm25 = Bm25Index(documents, k1=k1, b=b)
        self._query = QueryProcessor()
        self._default_limit = max(1, int(default_limit))
        self._max_limit = max(self._default_limit, int(max_limit))

    # -- corpus / indexing ----------------------------------------------------
    def index_documents(self, documents: Iterable[ProcessedDocument]) -> int:
        """Load *documents* into the BM25 index; returns the count indexed.

        Rebuilding is allowed (corpus reloads), but the common path builds once
        at startup via :func:`backend.pipeline.build_pipeline`.
        """
        docs = [d for d in documents]
        self._bm25 = Bm25Index(
            docs, k1=self._bm25._k1, b=self._bm25._b
        )
        return len(docs)

    @property
    def document_count(self) -> int:
        return self._bm25.document_count

    def corpus_stats(self) -> dict[str, object]:
        return self._bm25.stats

    def _rank_query(self, raw_query: str, limit: int) -> list[tuple[float, int]]:
        """Weighted tokens -> per-doc scores -> (score, doc-index) desc-sorted."""
        tokens = self._query.process(raw_query)
        if not tokens:
            return []
        qt = [w.token for w in tokens]
        scores = self._bm25.score(qt)
        ranked = sorted(
            enumerate(scores), key=lambda pair: (pair[1], -pair[0]), reverse=True
        )
        return [(score, idx) for idx, score in ranked[:limit]]

    # -- search ------------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        max_limit: int | None = None,
    ) -> SearchResponse:
        """Full ranked search; returns a frozen :class:`SearchResponse`."""
        start = time.perf_counter()
        limit = max(1, int(limit if limit is not None else self._default_limit))
        cap = int(max_limit if max_limit is not None else self._max_limit)
        limit = min(limit, cap)

        folded = self._query.normalize_query(query or "")
        docs = self._bm25.documents
        ranked = self._rank_query(folded, limit)

        hits: list[SearchResult] = []
        matched: set[str] = set()
        for rank, (score, idx) in enumerate(ranked, start=1):
            doc = docs[idx] if 0 <= idx < len(docs) else None
            if doc is None:
                continue
            tokens = [w.token for w in self._query.process(folded)]
            snippet = build_snippet(doc.content, tokens) if tokens else ""
            matched.update(t for t in tokens if t in doc.tokens)
            hits.append(
                SearchResult(
                    rank=rank,
                    document_id=doc.document_id,
                    title=doc.title,
                    source=doc.source,
                    snippet=snippet,
                    score=float(score),
                    matched_terms=tuple(sorted(set(tokens)))[:8],
                )
            )

        took_ms = (time.perf_counter() - start) * 1000.0
        response = SearchResponse(
            query=folded,
            total=len(hits),
            limit=limit,
            hits=tuple(hits),
            took_ms=took_ms,
            message="ok",
        )
        return response


__all__ = ["SearchEngine"]