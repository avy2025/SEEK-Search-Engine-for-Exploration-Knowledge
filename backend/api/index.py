"""Index administration API: fold crawled documents into the live engine.

``POST /api/index/rebuild`` merges the committed corpus with the Phase 4
crawler's stored pages, rebuilds an in-memory BM25 :class:`SearchEngine` and
swaps it into the running app (``backend.api.search.set_engine``) so searches
instantly include crawled content. PostgreSQL is never required.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.search import set_engine
from backend.crawler.service import get_crawl_manager
from backend.pipeline import build_pipeline

router = APIRouter(prefix="/api/index", tags=["index"])


class RebuildRequest(BaseModel):
    include_crawled: bool = True


@router.post("/rebuild", name="rebuild_index")
def rebuild_index(request: Optional[RebuildRequest] = None) -> dict[str, object]:
    """Rebuild the search index (corpus + crawled pages) and hot-swap it."""
    started = time.perf_counter()
    include_crawled = bool(request.include_crawled) if request else True
    extra = get_crawl_manager().store.to_processed_documents() if include_crawled else []
    engine = build_pipeline(extra=extra)
    set_engine(engine)
    took_ms = (time.perf_counter() - started) * 1000.0
    return {
        "documents_indexed": engine.document_count,
        "crawled_documents": len(extra),
        "corpus_documents": engine.document_count - len(extra),
        "include_crawled": include_crawled,
        "took_ms": round(took_ms, 3),
        "message": "index rebuilt; live server now searches corpus + crawled pages",
    }