"""Persistent repository for the single-user search history."""
from __future__ import annotations

import logging
from functools import lru_cache
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, BrowserSession, SearchHistory
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
            Base.metadata.create_all(
                self.engine,
                tables=[BrowserSession.__table__, SearchHistory.__table__],
            )
        except SQLAlchemyError as exc:
            logger.exception("Could not ensure the search_history table exists.")
            raise HistoryStoreUnavailable from exc

    def create_browser_session(
        self, token_hash: str, expires_at: datetime
    ) -> BrowserSession:
        try:
            with self._session_factory.begin() as session:
                browser_session = BrowserSession(
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
                session.add(browser_session)
                session.flush()
            return browser_session
        except SQLAlchemyError as exc:
            logger.exception("Could not create an anonymous browser session.")
            raise HistoryStoreUnavailable from exc

    def get_browser_session(
        self, token_hash: str, *, now: datetime
    ) -> Optional[BrowserSession]:
        try:
            with self._session_factory() as session:
                return session.scalar(
                    select(BrowserSession).where(
                        BrowserSession.token_hash == token_hash,
                        BrowserSession.expires_at > now,
                    )
                )
        except SQLAlchemyError as exc:
            logger.exception("Could not resolve an anonymous browser session.")
            raise HistoryStoreUnavailable from exc

    def create(
        self,
        query: str,
        mode: str,
        request_id: str,
        *,
        owner_session_id: str,
    ) -> SearchHistory:
        try:
            with self._session_factory.begin() as session:
                entry = SearchHistory(
                    id=request_id,
                    query=query,
                    mode=mode,
                    owner_session_id=owner_session_id,
                )
                session.add(entry)
                session.flush()
            return entry
        except IntegrityError as exc:
            try:
                with self._session_factory() as session:
                    existing = session.scalar(
                        select(SearchHistory).where(
                            SearchHistory.id == request_id,
                            SearchHistory.owner_session_id == owner_session_id,
                        )
                    )
            except SQLAlchemyError as lookup_exc:
                logger.exception("Could not verify an idempotent history write.")
                raise HistoryStoreUnavailable from lookup_exc
            if existing is None:
                raise HistoryIdempotencyConflict from exc
            if existing.query != query or existing.mode != mode:
                raise HistoryIdempotencyConflict from exc
            return existing
        except SQLAlchemyError as exc:
            logger.exception("Could not write a search history entry.")
            raise HistoryStoreUnavailable from exc

    def list(
        self,
        owner_session_id: str,
        *,
        limit: int,
        offset: int,
        mode: Optional[str] = None,
    ) -> tuple[list[SearchHistory], int]:
        try:
            with self._session_factory() as session:
                statement = select(SearchHistory).where(
                    SearchHistory.owner_session_id == owner_session_id
                )
                count_statement = select(func.count()).select_from(SearchHistory).where(
                    SearchHistory.owner_session_id == owner_session_id
                )
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

    def get(self, entry_id: str, *, owner_session_id: str) -> Optional[SearchHistory]:
        try:
            with self._session_factory() as session:
                return session.scalar(
                    select(SearchHistory).where(
                        SearchHistory.id == entry_id,
                        SearchHistory.owner_session_id == owner_session_id,
                    )
                )
        except SQLAlchemyError as exc:
            logger.exception("Could not read a search history entry.")
            raise HistoryStoreUnavailable from exc

    def delete(self, entry_id: str, *, owner_session_id: str) -> bool:
        try:
            with self._session_factory.begin() as session:
                entry = session.scalar(
                    select(SearchHistory).where(
                        SearchHistory.id == entry_id,
                        SearchHistory.owner_session_id == owner_session_id,
                    )
                )
                if entry is None:
                    return False
                session.delete(entry)
                return True
        except SQLAlchemyError as exc:
            logger.exception("Could not delete a search history entry.")
            raise HistoryStoreUnavailable from exc

    def clear(self, *, owner_session_id: str) -> int:
        try:
            with self._session_factory.begin() as session:
                result = session.execute(
                    delete(SearchHistory).where(
                        SearchHistory.owner_session_id == owner_session_id
                    )
                )
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            logger.exception("Could not clear search history.")
            raise HistoryStoreUnavailable from exc


@lru_cache(maxsize=1)
def get_history_repository() -> SearchHistoryRepository:
    """Use the same configured database as SEEK's document repository."""
    return SearchHistoryRepository()
