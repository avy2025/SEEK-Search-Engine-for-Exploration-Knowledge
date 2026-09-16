"""Phase 2 search endpoint: ``GET /api/search?q=...&limit=...&mode=...``.

The router delegates engine ownership to
:mod:`backend.search.index_manager` so lexical search always queries the same
live BM25 engine that ``/api/index/rebuild`` and ``/api/index/refresh`` swap at
runtime. When no persistent index exists yet the engine is empty and the
endpoint answers with ``hits: []`` and a clear ``message`` instead of faking
results.

Phase 6 adds the ``mode`` parameter:

* ``lexical`` / ``bm25`` (default) — the existing BM25 contract, unchanged;
* ``semantic`` — cosine-similarity search over the local FAISS index. When the
  embedding stack or the semantic index is unavailable, the endpoint returns the
  same envelope with ``hits: []`` and a structured ``semantic`` status block —
  it never silently falls back to BM25, so callers can tell "semantic
  unavailable" from "semantic returned zero results".
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query

from backend.search.embeddings import EmbeddingUnavailableError
from backend.search.engine import SearchEngine
from backend.search.index_manager import get_index_manager
from backend.search.models import SearchResponse
from backend.search.semantic import (
    get_semantic_index_manager,
)

router: APIRouter = APIRouter(prefix="/api/search", tags=["search"])


def _get_engine() -> SearchEngine:
    """Return the live search engine owned by the process-wide index manager."""
    return get_index_manager().engine


def set_engine(engine: SearchEngine) -> None:
    """Swap the live engine (kept for legacy/offline rebuild compatibility)."""
    get_index_manager().set_engine(engine)


def _hits_payload(response: SearchResponse) -> list[dict[str, object]]:
    return [
        {
            "rank": hit.rank,
            "document_id": hit.document_id,
            "title": hit.title,
            "source": hit.source,
            "snippet": hit.snippet,
            "score": round(float(hit.score), 4),
            "matched_terms": list(hit.matched_terms),
        }
        for hit in response.hits
    ]


def _semantic_search(q: str, limit: int) -> dict[str, object]:
    """Semantic mode: cosine-similarity FAISS search over local embeddings."""
    started = time.perf_counter()
    manager = get_semantic_index_manager()
    info = dict(manager.status())
    payload: dict[str, object] = {
        "query": q.strip(),
        "total": 0,
        "limit": limit,
        "hits": [],
        "took_ms": 0.0,
        "message": "",
        "mode": "semantic",
        "score_type": (
            "cosine_similarity (normalised embeddings; higher is more similar)"
        ),
        "semantic": info,
    }

    if not info.get("available"):
        payload["message"] = (
            "semantic search unavailable: " + str(info.get("message") or "")
        )
        payload["semantic"]["status"] = "unavailable"
        payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return payload

    try:
        response = manager.search(q, limit=limit, max_limit=50)
    except EmbeddingUnavailableError as exc:
        payload["message"] = f"semantic search unavailable: {exc}"
        payload["semantic"]["status"] = "unavailable"
        payload["semantic"]["reason"] = str(exc)
        payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return payload

    payload["query"] = response.query
    payload["total"] = response.total
    payload["hits"] = _hits_payload(response)
    payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    payload["message"] = response.message
    payload["semantic"]["status"] = (
        "not_built" if not info.get("loaded") else "ok"
    )
    return payload


def _lexical_search(q: str, limit: int) -> dict[str, object]:
    """Lexical mode: the original BM25 search contract (unchanged behaviour)."""
    started = time.perf_counter()
    engine = _get_engine()
    response: SearchResponse = engine.search(q, limit=limit, max_limit=50)
    took_ms = (time.perf_counter() - started) * 1000.0
    payload: dict[str, object] = {
        "query": response.query,
        "total": response.total,
        "limit": response.limit,
        "hits": _hits_payload(response),
        "took_ms": took_ms if took_ms else float(response.took_ms),
        "message": response.message,
        "mode": "lexical",
    }
    if engine.document_count == 0:
        payload["message"] = "index not built; run /api/index/rebuild"
    try:
        payload["semantic"] = get_semantic_index_manager().status()
    except Exception:  # noqa: BLE001 - status is best-effort on the BM25 path
        payload["semantic"] = {"available": False, "message": "semantic status unavailable"}
    return payload


@router.get("", name="search")
def search_documents(
    q: str = Query(..., min_length=1, description="Free-text query"),
    limit: int = Query(10, ge=1, le=50, description="Max hits to return"),
    mode: str = Query(
        "lexical",
        pattern="^(lexical|bm25|semantic)$",
        description="Search mode: lexical/bm25 (default) or semantic",
    ),
) -> dict[str, object]:
    """Ranked hits for *q* in the requested mode (stable JSON envelope)."""
    if mode == "semantic":
        return _semantic_search(q, limit)
    return _lexical_search(q, limit)


__all__ = [
    "router",
    "search_documents",
    "_get_engine",
    "set_engine",
    "_lexical_search",
    "_semantic_search",
]