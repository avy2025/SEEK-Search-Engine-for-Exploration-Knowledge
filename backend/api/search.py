"""Phase 2 search endpoint: ``GET /api/search?q=...&limit=...``.

Self-contained and dependency-light on purpose: the router builds the shared
BM25 engine once (module-level, process lifetime) and every request maps the
verified :mod:`backend.search.models` dataclasses straight to a plain dict, so
this module needs nothing but FastAPI + the already-probed ``backend.pipeline``
and ``backend.search`` packages. Phase 1 ``backend.api.router`` stays untouched;
Phase 2 registers this router only when the app imports it from ``main.py``.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query

from backend.pipeline import build_pipeline
from backend.search.engine import SearchEngine
from backend.search.models import SearchResponse

router: APIRouter = APIRouter(prefix="/api/search", tags=["search"])

# Process-wide singleton; initialised lazily on first request so the probe/app
# build never need a live corpus or database to import the route table.
_engine: Optional[SearchEngine] = None


def _get_engine() -> SearchEngine:
    global _engine
    if _engine is None:
        _engine = build_pipeline()
    return _engine


@router.get("", name="search")
def search_documents(
    q: str = Query(..., min_length=1, description="Free-text query"),
    limit: int = Query(10, ge=1, le=50, description="Max hits to return"),
) -> dict[str, object]:
    """Ranked BM25 hits for *q* (Phase 2 envelope, stable JSON)."""
    started = time.perf_counter()
    response: SearchResponse = _get_engine().search(q, limit=limit, max_limit=50)
    took_ms = (time.perf_counter() - started) * 1000.0
    return {
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


__all__ = ["router", "search_documents", "_get_engine"]
