"""Phase 2 search endpoint: ``GET /api/search?q=...&limit=...``.

The router delegates engine ownership to
:mod:`backend.search.index_manager` so search always queries the same live
engine that ``/api/index/rebuild`` and ``/api/index/refresh`` swap at
runtime. When no persistent index exists yet the engine is empty and the
endpoint answers with ``hits: []`` and a clear ``message`` instead of faking
results.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query

from backend.search.engine import SearchEngine
from backend.search.index_manager import get_index_manager
from backend.search.models import SearchResponse

router: APIRouter = APIRouter(prefix="/api/search", tags=["search"])


def _get_engine() -> SearchEngine:
    """Return the live search engine owned by the process-wide index manager."""
    return get_index_manager().engine


def set_engine(engine: SearchEngine) -> None:
    """Swap the live engine (kept for legacy/offline rebuild compatibility)."""
    get_index_manager().set_engine(engine)


@router.get("", name="search")
def search_documents(
    q: str = Query(..., min_length=1, description="Free-text query"),
    limit: int = Query(10, ge=1, le=50, description="Max hits to return"),
) -> dict[str, object]:
    """Ranked BM25 hits for *q* (Phase 2 envelope, stable JSON)."""
    started = time.perf_counter()
    engine = _get_engine()
    response: SearchResponse = engine.search(q, limit=limit, max_limit=50)
    took_ms = (time.perf_counter() - started) * 1000.0
    payload: dict[str, object] = {
        "query": response.query,
        "total": response.total,
        "limit": response.limit,
        "hits": [
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
        ],
        "took_ms": took_ms if took_ms else float(response.took_ms),
        "message": response.message,
    }
    if engine.document_count == 0:
        payload["message"] = "index not built; run /api/index/rebuild"
    return payload


__all__ = ["router", "search_documents", "_get_engine", "set_engine"]
