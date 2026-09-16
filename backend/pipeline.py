"""Phase 2 corpus -> index -> API orchestration (single source of truth).

``backend.pipeline`` is the one place that deliberately couples the corpus
loader, the BM25 engine and optional persistence together. It never raises on
infrastructure failures: the in-memory BM25 index is the authority for Phase 2
and PostgreSQL is a strict best-effort cache.

Design notes
------------
* ``build_pipeline()`` is the single Phase 2 entry point — it loads the corpus,
  (re)builds the index and returns a ready :class:`SearchEngine`.
* ``run_pipeline`` records a small best-effort ``PipelineReport`` (pure data) so
  callers/tests can assert on what happened without touching the database.
* All repository/session work is deferred to ``backend.db.repository_factory``;
  this module only ever needs the repository's public surface, so the import
  graph stays flat and phase-1 tests keep passing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings
from backend.db.session import Database, make_database_engine
from backend.db.repository import make_document_repository
from backend.db.repository_factory import (
    create_initialised_document_repository,
)
from backend.processing.loader import load_corpus
from backend.processing.models import ProcessedDocument
from backend.search.bm25 import Bm25
from backend.search.engine import SearchEngine

logger = logging.getLogger("seek.pipeline")

__all__ = [
    "PipelineReport",
    "SearchEngine",
    "build_pipeline",
    "run_pipeline",
    "persist_corpus",
]


@dataclass(frozen=True)
class PipelineReport:
    """Human/diagnostic summary of one pipeline run (pure data)."""

    documents_loaded: int = 0
    indexed: int = 0
    persisted: int = 0
    took_ms: float = 0.0
    message: str = ""


def build_pipeline(
    extra: Optional[list[ProcessedDocument]] = None,
) -> SearchEngine:
    """Load the corpus and return an indexed :class:`SearchEngine`.

    *extra* may carry additional :class:`ProcessedDocument` values (e.g. from
    the Phase 4 crawler) that are appended to the committed corpus before
    indexing. The engine always lands (in-memory BM25); persistence is
    attempted best-effort and failures are swallowed. PostgreSQL availability is
    never a precondition for returning a useful search engine.
    """
    processed = load_corpus()
    if extra:
        processed = processed + [
            d for d in extra if d is not None and d.content and d.tokens
        ]
    engine = SearchEngine()
    engine.index_documents(processed)
    return engine


def run_pipeline(report: Optional[PipelineReport] = None) -> PipelineReport:
    """Index the corpus plus a best-effort persist, returning the report."""
    import time

    start = time.perf_counter()
    processed = load_corpus()
    engine = SearchEngine()
    engine.index_documents(processed)
    persisted = _persist_best_effort(processed)
    took_ms = (time.perf_counter() - start) * 1000.0
    message = "indexed %d documents in-memory"
    if persisted:
        message += " (+%d persisted)"
    return PipelineReport(
        documents_loaded=len(processed),
        indexed=len(processed),
        persisted=persisted,
        took_ms=took_ms,
        message=message % (len(processed), persisted) if persisted else message % len(processed),
    )


def persist_corpus(repository: Optional["DocumentRepository"] = None) -> int:
    """Ensure the committed corpus is present in PostgreSQL (idempotent).

    The Phase 5B index builder calls this *before* reconstructing the BM25
    index so the canonical PostgreSQL document set always includes the local
    sample corpus. Rows already present (matching ``content_hash``) are
    skipped, so repeated calls are cheap. Returns the number of rows newly
    inserted (0 when everything already exists or PostgreSQL is unavailable).
    Never raises.
    """
    from backend.db.models import Document

    repo = repository
    if repo is None:
        try:
            repo = create_initialised_document_repository(settings.DATABASE_URL)
        except Exception as exc:  # noqa: BLE001 - corpus persist is optional
            logger.debug("corpus persist skipped, repository unavailable: %s", exc)
            return 0
    if repo is None or not getattr(repo, "is_available", lambda: False)():
        return 0
    docs = [
        Document(
            title=d.title,
            content=d.content,
            source=d.source,
            content_hash=d.content_hash or "",
        )
        for d in load_corpus()
    ]
    try:
        return repo.upsert_many(docs)
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.debug("corpus persist skipped: %s", exc)
        return 0


def _persist_best_effort(documents: list[ProcessedDocument]) -> int:
    """Try to persist *documents* through the repository; return count or 0."""
    repository = None
    try:
        repo = create_initialised_document_repository(settings.DATABASE_URL)
        if repo is not None and getattr(repo, "is_available", lambda: False)():
            repository = repo
    except Exception as exc:  # noqa: BLE001 - DB is optional; never crash
        logger.debug("repository unavailable, skipping persist: %s", exc)
        return 0
    if repository is None:
        return 0
    from backend.db.models import Document

    docs = [
        Document(
            title=d.title,
            content=d.content,
            source=d.source,
            content_hash=d.content_hash or "",
        )
        for d in documents
    ]
    try:
        return repository.upsert_many(docs)
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.debug("bulk persist skipped: %s", exc)
        return 0
