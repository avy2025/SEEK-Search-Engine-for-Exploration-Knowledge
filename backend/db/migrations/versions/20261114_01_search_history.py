"""Create persistent search history.

Revision ID: 20261114_01
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "20261114_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("search_history"):
        return

    op.create_table(
        "search_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="completed",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('web', 'ai', 'research', 'code', 'live')",
            name="ck_search_history_mode",
        ),
        sa.CheckConstraint(
            "status = 'completed'",
            name="ck_search_history_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_history_created_at", "search_history", ["created_at"]
    )
    op.create_index(
        "ix_search_history_mode_created_at",
        "search_history",
        ["mode", "created_at"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("search_history"):
        op.drop_table("search_history")
