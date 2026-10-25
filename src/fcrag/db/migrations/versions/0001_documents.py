"""documents registry

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("source_key", sa.String(255), primary_key=True),
        sa.Column("doc_id", sa.String(200), nullable=False),
        sa.Column("doc_version", sa.Integer, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("doc_type", sa.String(40)),
        sa.Column("system", sa.String(40)),
        sa.Column("language", sa.String(8)),
        sa.Column("licence", sa.Text),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("element_count", sa.Integer),
        sa.Column("chunk_count", sa.Integer),
        sa.Column("indexed_sha256", sa.String(64)),
        sa.Column("duration_s", sa.Float),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_doc_id", "documents", ["doc_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_doc_id", table_name="documents")
    op.drop_table("documents")
