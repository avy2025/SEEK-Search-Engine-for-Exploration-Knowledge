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

from backend.config import settings
from backend.search.embeddings import EmbeddingUnavailableError
from backend.search.engine import SearchEngine
from backend.search.hybrid import (
    InvalidHybridWeightsError,
    merge_and_rerank_hybrid,
    validate_and_normalize_weights,
)
from backend.search.index_manager import get_index_manager
from backend.search.models import SearchResponse, SearchResult
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


def _hybrid_search(
    q: str,
    limit: int,
    bm25_weight: float | None = None,
    semantic_weight: float | None = None,
) -> dict[str, object]:
    """Hybrid mode: merge BM25 and Semantic candidates with score normalization."""
    started = time.perf_counter()
    bm25_manager = get_index_manager()
    sem_manager = get_semantic_index_manager()

    bm25_status = bm25_manager.status()
    sem_status = dict(sem_manager.status())

    bm25_avail = bool(bm25_manager.engine.document_count > 0 or bm25_status.get("loaded"))
    sem_avail = bool(sem_status.get("available") and sem_status.get("loaded"))

    try:
        norm_w = validate_and_normalize_weights(bm25_weight, semantic_weight)
    except InvalidHybridWeightsError as exc:
        took_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return {
            "query": q.strip(),
            "total": 0,
            "limit": limit,
            "hits": [],
            "took_ms": took_ms,
            "message": f"invalid hybrid configuration: {exc}",
            "mode": "hybrid",
            "weights": {
                "bm25": bm25_weight if bm25_weight is not None else settings.HYBRID_BM25_WEIGHT,
                "semantic": semantic_weight if semantic_weight is not None else settings.HYBRID_SEMANTIC_WEIGHT,
            },
            "status": "error",
        }

    weights_dict = {"bm25": round(norm_w.bm25, 4), "semantic": round(norm_w.semantic, 4)}

    payload: dict[str, object] = {
        "query": q.strip(),
        "total": 0,
        "limit": limit,
        "hits": [],
        "took_ms": 0.0,
        "message": "",
        "mode": "hybrid",
        "weights": weights_dict,
        "bm25_status": bm25_status,
        "semantic_status": sem_status,
    }

    if not bm25_avail and not sem_avail:
        payload["message"] = "hybrid search unavailable: both BM25 and semantic indexes are not available"
        payload["status"] = "unavailable"
        payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return payload

    if not bm25_avail:
        payload["message"] = "hybrid search degraded/unavailable: BM25 index is not available"
        payload["status"] = "degraded"
        payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return payload

    if not sem_avail:
        sem_msg = str(sem_status.get("message") or "semantic index not loaded/available")
        payload["message"] = f"hybrid search degraded/unavailable: {sem_msg}"
        payload["status"] = "degraded"
        payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return payload

    cand_bm25_limit = max(limit, settings.HYBRID_BM25_CANDIDATES)
    cand_sem_limit = max(limit, settings.HYBRID_SEMANTIC_CANDIDATES)

    bm25_resp = bm25_manager.engine.search(q, limit=cand_bm25_limit, max_limit=100)

    try:
        sem_resp = sem_manager.search(q, limit=cand_sem_limit, max_limit=100)
    except EmbeddingUnavailableError as exc:
        payload["message"] = f"hybrid search degraded/unavailable: semantic search failed ({exc})"
        payload["status"] = "degraded"
        payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return payload

    merged_hits, final_weights = merge_and_rerank_hybrid(
        bm25_hits=bm25_resp.hits,
        semantic_hits=sem_resp.hits,
        query=q,
        limit=limit,
        bm25_weight=norm_w.bm25,
        semantic_weight=norm_w.semantic,
    )

    payload["query"] = bm25_resp.query or q.strip()
    payload["total"] = len(merged_hits)
    payload["hits"] = _hits_payload(SearchResponse(
        query=payload["query"],
        total=len(merged_hits),
        limit=limit,
        hits=tuple(merged_hits),
    ))
    payload["took_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    payload["message"] = "ok"
    payload["status"] = "ok"
    payload["weights"] = final_weights
    return payload


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
        pattern="^(lexical|bm25|semantic|hybrid)$",
        description="Search mode: lexical/bm25 (default), semantic, or hybrid",
    ),
    bm25_weight: float | None = Query(None, ge=0.0, description="Optional BM25 hybrid weight"),
    semantic_weight: float | None = Query(None, ge=0.0, description="Optional Semantic hybrid weight"),
) -> dict[str, object]:
    """Ranked hits for *q* in the requested mode (stable JSON envelope)."""
    if mode == "hybrid":
        return _hybrid_search(q, limit, bm25_weight, semantic_weight)
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