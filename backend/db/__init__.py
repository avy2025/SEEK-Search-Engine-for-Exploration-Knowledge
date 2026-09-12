"""SEEK persistence layer (Phase 2).

SQLAlchemy ORM models + best-effort PostgreSQL sessions. The database is fully
optional for Phase 2 search: when Postgres is unreachable the system degrades to
an in-memory BM25 index and simply skips persistence.
"""

from backend.db.models import Document
from backend.db.repository import DocumentRepository
from backend.db.repository_factory import (
    create_document_repository,
    create_initialised_document_repository,
)
from backend.db.session import Database, make_database_engine

__all__ = [
    "Document",
    "DocumentRepository",
    "Database",
    "make_database_engine",
    "create_document_repository",
    "create_initialised_document_repository",
]
