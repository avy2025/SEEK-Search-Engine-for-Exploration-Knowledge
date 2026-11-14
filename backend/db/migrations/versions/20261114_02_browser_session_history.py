"""Scope search history to anonymous browser sessions.

Revision ID: 20261114_02
Revises: 20261114_01
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "20261114_02"
down_revision = "20261114_01"
branch_labels = None
depends_on = None


def _create_browser_sessions() -> None:
    if sa.inspect(op.get_bind()).has_table("browser_sessions"):
        return
    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_browser_sessions_token_hash",
        "browser_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"]
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("search_history"):
        return

    _create_browser_sessions()
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("search_history")}
    if "owner_session_id" in columns:
        return

    op.add_column(
        "search_history",
        sa.Column("owner_session_id", sa.String(length=36), nullable=True),
    )
    bind = op.get_bind()
    unowned_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM search_history WHERE owner_session_id IS NULL"
        )
    ).scalar_one()
    if unowned_count:
        quarantine_id = str(uuid4())
        quarantined_token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        bind.execute(
            sa.text(
                "INSERT INTO browser_sessions (id, token_hash, expires_at) "
                "VALUES (:id, :token_hash, :expires_at)"
            ),
            {
                "id": quarantine_id,
                "token_hash": quarantined_token_hash,
                "expires_at": expired_at.isoformat(),
            },
        )
        bind.execute(
            sa.text(
                "UPDATE search_history SET owner_session_id = :owner_id "
                "WHERE owner_session_id IS NULL"
            ),
            {"owner_id": quarantine_id},
        )

    with op.batch_alter_table("search_history") as batch:
        batch.alter_column(
            "owner_session_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_search_history_owner_session_id_browser_sessions",
            "browser_sessions",
            ["owner_session_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_search_history_owner_created_at",
            ["owner_session_id", "created_at"],
        )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("search_history"):
        return
    # Older revisions expose history without an owner; never leave owned rows
    # readable through the pre-session API during a rollback.
    op.execute(sa.text("DELETE FROM search_history"))
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("search_history")}
    if "owner_session_id" in columns:
        with op.batch_alter_table("search_history") as batch:
            batch.drop_index("ix_search_history_owner_created_at")
            batch.drop_constraint(
                "fk_search_history_owner_session_id_browser_sessions",
                type_="foreignkey",
            )
            batch.drop_column("owner_session_id")
    if sa.inspect(op.get_bind()).has_table("browser_sessions"):
        op.drop_table("browser_sessions")
