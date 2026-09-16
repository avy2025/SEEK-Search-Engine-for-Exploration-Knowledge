"""Best-effort persistence repository for SEEK Phase 2.

SEEK's search MVP is *corpus-first*: the in-memory BM25 index is the authority
and PostgreSQL is an optional durable cache. Every method on
:class:`DocumentRepository` therefore degrades gracefully — when the database is
unreachable it returns ``False``/empty results instead of raising, so the search
API keeps working purely from the BM25 index.

This mirrors the Phase 1 contract (``backend.db.repository``) so the Phase 2
probe and Phase 1 tests both resolve the same repository symbols.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.db.models import Document

logger = logging.getLogger("seek.db.repository")


def make_document_repository(session: Optional[Session] = None) -> "DocumentRepository":
    """Phase 2 factory: build a :class:`DocumentRepository` over *session*.

    Kept as a module-level helper so ``backend.db.repository_factory`` and
    ``backend.db.session`` both resolve a single, stable symbol from
    ``backend.db.repository`` (mirrors the Phase 1 contract).
    """
    return DocumentRepository(session)


class DocumentRepository:
    """SQLAlchemy-backed repository over the ``documents`` table.

    Session is provided by the caller (see ``backend.db.session``); the
    repository itself never opens connections, keeping it test-friendly.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session

    @property
    def session(self) -> Optional[Session]:
        return self._session

    def is_available(self) -> bool:
        """True when the underlying database answers a trivial query."""
        if self._session is None:
            return False
        try:
            self._session.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # noqa: BLE001 - degraded path is intentional
            logger.debug("Database availability check failed: %s", exc)
            return False

    def upsert(self, document: Document) -> bool:
        """Insert *document* (dedup by ``content_hash``); never raises."""
        if self._session is None:
            return False
        try:
            existing = self.find_by_content_hash(document.content_hash)
            if existing is not None:
                return False
            self._session.add(document)
            self._session.flush()
            self._session.commit()
            return True
        except SQLAlchemyError as exc:  # pragma: no cover - depends on live DB
            logger.warning("upsert skipped: %s", exc)
            self._session.rollback()
            return False

    def upsert_many(self, documents: list[Document]) -> int:
        """Persist *documents*, returning how many were actually inserted."""
        inserted = 0
        for doc in documents:
            if self.upsert(doc):
                inserted += 1
        return inserted

    def find_by_content_hash(self, content_hash: str) -> Optional[Document]:
        if self._session is None:
            return None
        try:
            return self._session.scalars(
                select(Document).where(Document.content_hash == content_hash)
            ).first()
        except SQLAlchemyError as exc:  # pragma: no cover - depends on live DB
            logger.warning("find_by_content_hash skipped: %s", exc)
            return None

    def count(self) -> int:
        """Total number of persisted documents (0 when unavailable)."""
        if self._session is None:
            return 0
        try:
            return int(
                self._session.scalar(select(func.count()).select_from(Document)) or 0
            )
        except SQLAlchemyError as exc:  # pragma: no cover - depends on live DB
            logger.warning("count skipped: %s", exc)
            return 0

    def list_all(self, *, limit: Optional[int] = None) -> list[Document]:
        """Return every persisted document in deterministic ``document_id`` order.

        Used by the Phase 5B index builder to reconstruct the BM25 index from
        PostgreSQL. Never raises: returns ``[]`` when unavailable.
        """
        if self._session is None:
            return []
        try:
            stmt = select(Document).order_by(Document.document_id)
            if limit is not None:
                stmt = stmt.limit(max(0, int(limit)))
            return list(self._session.scalars(stmt))
        except SQLAlchemyError as exc:  # pragma: no cover - depends on live DB
            logger.warning("list_all skipped: %s", exc)
            return []

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
