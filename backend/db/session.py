from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.db.models import Base

logger = logging.getLogger("seek.db.session")


def make_database_engine(database_url: Optional[str] = None) -> Engine:
    """Create a SQLAlchemy engine for the configured PostgreSQL database.

    A short ``connect_timeout`` keeps app startup snappy and lets the rest of
    SEEK run purely from the in-memory BM25 index when Postgres is unavailable.
    """
    url = database_url or settings.DATABASE_URL
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 6},
    )


class Database:
    """Thin wrapper around a SQLAlchemy engine + scoped session factory."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        create_tables: bool = True,
    ) -> None:
        self.engine: Engine = make_database_engine(database_url)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        if create_tables:
            try:
                Base.metadata.create_all(self.engine)
                logger.info("Database tables ensured.")
            except Exception as exc:  # pragma: no cover - depends on live Postgres
                logger.warning("Could not create database tables: %s", exc)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def is_available(self) -> bool:
        """Best-effort probe; returns False when Postgres is unreachable."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - depends on live Postgres
            logger.debug("Database unavailable: %s", exc)
            return False


def create_database(database_url: Optional[str] = None) -> Database:
    return Database(database_url)
