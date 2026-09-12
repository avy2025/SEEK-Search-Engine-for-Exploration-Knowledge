"""Best-effort, never-blocks repository construction for SEEK Phase 2.

The search API must keep answering from the in-memory BM25 index even when
Postgres is unreachable (``docker compose`` cold starts, local dev without
``db``, CI without Postgres). Everything in this module therefore degrades
***instead of raising***, so neither the FastAPI lifespan nor the probe/build
path can be killed by a missing database.

Public entry points (all never raise):
* :func:`create_best_effort_repository`
* :func:`create_initialised_document_repository`  (Phase 2 preferred)
* :func:`create_document_repository_factory`      (Phase 1 alias)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from time import sleep

from backend.config import settings
from backend.db.repository import (
    DocumentRepository,
    make_document_repository,
)
from backend.db.session import Database

logger = logging.getLogger("seek.db.repository_factory")


def _attempt_repository(database_url: Optional[str] = None) -> Optional[DocumentRepository]:
    """Best-effort: build a live repository, or return ``None`` (never raises)."""
    try:
        if database_url is None:
            database_url = settings.DATABASE_URL
        database = Database(database_url)
        repo = make_document_repository(database)
        if repo.is_available():
            return repo
        logger.info("Database available; returning degraded repository.")
        return repo
    except Exception as exc:  # noqa: BLE001 - never propagate DB problems
        logger.debug("Repository build skipped (%s); running degraded.", exc)
        return None


def _degraded_repository() -> DocumentRepository:
    """Stand-in repository for the (common) no-Postgres case."""
    return make_document_repository(None)


def create_best_effort_repository(database_url: Optional[str] = None) -> DocumentRepository:
    """Try to build a live repository, else return a degraded no-op one."""
    repo = _attempt_repository(database_url)
    if repo is not None:
        return repo
    return _degraded_repository()


def create_initialised_document_repository(
    database_url: Optional[str] = None,
    *,
    attempts: int = 3,
    delay_seconds: float = 0.5,
) -> DocumentRepository:
    """Initialised repository with a few cheap retries for cold-start Postgres."""
    last = None
    for attempt in range(max(1, int(attempts))):
        repo = _attempt_repository(database_url)
        if repo is not None and repo.is_available():
            return repo
        last = repo
        if attempt < max(1, int(attempts)) - 1:
            sleep(float(delay_seconds))
    if last is not None:
        return last
    return _degraded_repository()


def create_document_repository(
    database_url: Optional[str] = None,
) -> DocumentRepository:
    """Phase 2 entry point: a ready-to-use repository (never raises)."""
    return create_best_effort_repository(database_url)


def create_document_repository_factory(
    database_url: Optional[str] = None,
) -> Callable[[], DocumentRepository]:
    """Zero-arg factory (Phase 1 wiring spelling) wrapping the same logic.

    Returns a callable that, when invoked, returns a repository — degraded
    repository included. Used by ``backend.api`` Phase 1 health wiring and by
    tests that freeze a factory.
    """

    def _factory() -> DocumentRepository:
        return create_best_effort_repository(database_url)

    return _factory


__all__ = [
    "create_best_effort_repository",
    "create_initialised_document_repository",
    "create_document_repository_factory",
]
