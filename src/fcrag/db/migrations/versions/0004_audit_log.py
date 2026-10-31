"""audit log

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(200)),
        sa.Column("groups", sa.JSON),
        sa.Column("endpoint", sa.String(40), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("search_question", sa.Text),
        sa.Column("answer", sa.Text),
        sa.Column("found", sa.Boolean),
        sa.Column("cached", sa.Boolean, nullable=False),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(40)),
        sa.Column("trace_id", sa.String(64)),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", "audit_log")
    op.drop_table("audit_log")
