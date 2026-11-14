"""Persistent repository for the single-user search history."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, SearchHistory
from backend.db.session import make_database_engine

logger = logging.getLogger("seek.db.history")


class HistoryStoreUnavailable(Exception):
    """Raised when the configured database cannot serve history operations."""


class HistoryIdempotencyConflict(Exception):
    """Raised when an idempotency key is reused for different search data."""


class SearchHistoryRepository:
    """Small SQLAlchemy repository, bound to SEEK's configured document DB."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self.engine = engine or make_database_engine()
        self._session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        try:
            Base.metadata.create_all(self.engine, tables=[SearchHistory.__table__])
        except SQLAlchemyError as exc:
            logger.exception("Could not ensure the search_history table exists.")
            raise HistoryStoreUnavailable from exc

    def create(self, query: str, mode: str, request_id: str) -> SearchHistory:
        try:
            with self._session_factory.begin() as session:
                entry = SearchHistory(id=request_id, query=query, mode=mode)
                session.add(entry)
                session.flush()
            return entry
        except IntegrityError as exc:
            try:
                with self._session_factory() as session:
                    existing = session.get(SearchHistory, request_id)
            except SQLAlchemyError as lookup_exc:
                logger.exception("Could not verify an idempotent history write.")
                raise HistoryStoreUnavailable from lookup_exc
            if existing is None:
                logger.exception("Could not write a search history entry.")
                raise HistoryStoreUnavailable from exc
            if existing.query != query or existing.mode != mode:
                raise HistoryIdempotencyConflict from exc
            return existing
        except SQLAlchemyError as exc:
            logger.exception("Could not write a search history entry.")
            raise HistoryStoreUnavailable from exc

    def list(
        self, *, limit: int, offset: int, mode: Optional[str] = None
    ) -> tuple[list[SearchHistory], int]:
        try:
            with self._session_factory() as session:
                statement = select(SearchHistory)
                count_statement = select(func.count()).select_from(SearchHistory)
                if mode is not None:
                    statement = statement.where(SearchHistory.mode == mode)
                    count_statement = count_statement.where(SearchHistory.mode == mode)
                entries = session.scalars(
                    statement.order_by(
                        SearchHistory.created_at.desc(), SearchHistory.id.desc()
                    )
                    .limit(limit)
                    .offset(offset)
                ).all()
                total = int(session.scalar(count_statement) or 0)
                return list(entries), total
        except SQLAlchemyError as exc:
            logger.exception("Could not read search history.")
            raise HistoryStoreUnavailable from exc

    def get(self, entry_id: str) -> Optional[SearchHistory]:
        try:
            with self._session_factory() as session:
                return session.get(SearchHistory, entry_id)
        except SQLAlchemyError as exc:
            logger.exception("Could not read a search history entry.")
            raise HistoryStoreUnavailable from exc

    def delete(self, entry_id: str) -> bool:
        try:
            with self._session_factory.begin() as session:
                entry = session.get(SearchHistory, entry_id)
                if entry is None:
                    return False
                session.delete(entry)
                return True
        except SQLAlchemyError as exc:
            logger.exception("Could not delete a search history entry.")
            raise HistoryStoreUnavailable from exc

    def clear(self) -> int:
        try:
            with self._session_factory.begin() as session:
                result = session.execute(delete(SearchHistory))
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            logger.exception("Could not clear search history.")
            raise HistoryStoreUnavailable from exc


@lru_cache(maxsize=1)
def get_history_repository() -> SearchHistoryRepository:
    """Use the same configured database as SEEK's document repository."""
    return SearchHistoryRepository()
