"""SQLAlchemy ORM model layer for SEEK.

``Base`` is the single regicle-registry metadata object shared by every table; it
is defined **here** (``backend.db.models``) and imported by ``backend.db.session``
so there is exactly one direction of dependency — ``session -> models`` — and no
import cycle.

The ORM stores indexed documents and the minimal query metadata needed for the
single-user search history. Search authority stays in the in-memory BM25 index.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for every SEEK table."""


class Document(Base):
    """A single persisted corpus document."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_content_hash", "content_hash", unique=True),
        Index("ix_documents_source", "source"),
    )

    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial debug helper
        return f"<Document id={self.document_id} title={self.title!r}>"


class SearchHistory(Base):
    """One completed user search, without provider responses or credentials."""

    __tablename__ = "search_history"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('web', 'ai', 'research', 'code', 'live')",
            name="ck_search_history_mode",
        ),
        CheckConstraint(
            "status = 'completed'",
            name="ck_search_history_status",
        ),
        Index("ix_search_history_created_at", "created_at"),
        Index("ix_search_history_mode_created_at", "mode", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="completed", server_default="completed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
