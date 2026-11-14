from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.db.models import Base

logger = logging.getLogger("seek.db.session")


def make_database_engine(database_url: Optional[str] = None) -> Engine:
    """Create an engine for the configured PostgreSQL or local SQLite database.

    A short ``connect_timeout`` keeps app startup snappy and lets the rest of
    SEEK run purely from the in-memory BM25 index when Postgres is unavailable.
    """
    url = database_url or settings.DATABASE_URL
    parsed_url = make_url(url)
    options: dict[str, object] = {"pool_pre_ping": True}
    if parsed_url.get_backend_name() == "sqlite":
        options["connect_args"] = {"timeout": 6}
        if parsed_url.database not in (None, "", ":memory:"):
            options.update(pool_size=5, max_overflow=10)
    else:
        options.update(
            pool_size=5,
            max_overflow=10,
            connect_args={"connect_timeout": 6},
        )
    return create_engine(url, **options)


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
