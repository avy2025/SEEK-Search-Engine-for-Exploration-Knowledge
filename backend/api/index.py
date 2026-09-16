"""Index administration API (Phase 5B).

PostgreSQL is the canonical document source; the BM25 index under
``indexes/bm25`` is a derived, persistent artifact. These endpoints manage
that lifecycle:

* ``POST /api/index/rebuild`` — read every document from PostgreSQL, rebuild
  the BM25 model, persist the artifact atomically and hot-swap the live engine.
  When PostgreSQL is unreachable it falls back to the legacy in-memory
  corpus + crawl-store build so the Phase 4 offline contract keeps working
  (that fallback is never persisted).
* ``POST /api/index/refresh`` — compare the PostgreSQL ``document_id ->
  content_hash`` set against the persisted index metadata and rebuild only
  when something changed (incremental change detection with full BM25
  reconstruction, never a true incremental BM25 update).
* ``GET /api/index/status`` — safe report of index/DB state in every
  environmental edge case (missing/corrupt index, no PostgreSQL, no docs).
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.search import set_engine
from backend.crawler.service import get_crawl_manager
from backend.pipeline import build_pipeline
from backend.search.index_manager import (
    IndexUnavailableError,
    get_index_manager,
)

router = APIRouter(prefix="/api/index", tags=["index"])


class RebuildRequest(BaseModel):
    include_crawled: bool = True


@router.post("/rebuild", name="rebuild_index")
def rebuild_index(request: Optional[RebuildRequest] = None) -> dict[str, object]:
    """Rebuild the persistent index from PostgreSQL and hot-swap it."""
    started = time.perf_counter()
    include_crawled = bool(request.include_crawled) if request else True
    manager = get_index_manager()
    try:
        result = manager.rebuild(include_crawled=include_crawled)
    except IndexUnavailableError:
        return _legacy_rebuild(include_crawled, started)
    took_ms = (time.perf_counter() - started) * 1000.0
    return {
        "status": result.status,
        "documents_indexed": result.documents_indexed,
        "crawled_documents": result.crawled_documents,
        "corpus_documents": result.documents_indexed - result.crawled_documents,
        "index_version": result.index_version,
        "built_at": result.built_at,
        "updated_at": result.updated_at,
        "source": result.source,
        "include_crawled": include_crawled,
        "took_ms": round(took_ms, 3),
        "message": result.message,
    }


@router.post("/refresh", name="refresh_index")
def refresh_index() -> dict[str, object]:
    """Rebuild only when new/modified/deleted documents are detected."""
    started = time.perf_counter()
    result = get_index_manager().refresh()
    took_ms = (time.perf_counter() - started) * 1000.0
    return {
        "status": result.status,
        "document_count": result.document_count,
        "index_version": result.index_version,
        "changed": result.changed,
        "message": result.message,
        "took_ms": round(took_ms, 3),
    }


@router.get("/status", name="index_status")
def index_status() -> dict[str, object]:
    """Report the current persistent index / database state (never raises)."""
    return get_index_manager().status()


def _legacy_rebuild(include_crawled: bool, started: float) -> dict[str, object]:
    """Offline fallback: PostgreSQL is down, so rebuild from local sources."""
    extra = get_crawl_manager().store.to_processed_documents() if include_crawled else []
    engine = build_pipeline(extra=extra)
    set_engine(engine)
    took_ms = (time.perf_counter() - started) * 1000.0
    return {
        "status": "rebuilt",
        "documents_indexed": engine.document_count,
        "crawled_documents": len(extra),
        "corpus_documents": engine.document_count - len(extra),
        "index_version": None,
        "built_at": None,
        "updated_at": None,
        "source": "legacy_corpus",
        "include_crawled": include_crawled,
        "took_ms": round(took_ms, 3),
        "message": (
            "PostgreSQL unavailable; index rebuilt from local corpus + crawl "
            "store (not persisted to indexes/)"
        ),
    }