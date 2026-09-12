"""BM25 ranked search package (SEEK Phase 2).

Public surface
--------------
* :class:`~backend.search.models.SearchResult` — one ranked hit sent to the client.
* :class:`~backend.search.models.SearchResponse` — the Phase 2 wire envelope.
* :class:`~backend.search.bm25.Bm25Index` — BM25 over the token stream of each
  processed document (PreparedProcessedDocument).
* :class:`~backend.search.engine.SearchEngine` — the single Phase 2 point of
  entry used by ``backend.pipeline`` and the FastAPI app.
"""
from __future__ import annotations

from backend.search.models import SearchResult, SearchResponse, SearchQuery
from backend.search.query import QueryProcessor

__all__ = [
    "SearchResult",
    "SearchResponse",
    "SearchQuery",
    "QueryProcessor",
]
