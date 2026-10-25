"""parameters

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parameters",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("system", sa.String(40), nullable=False),
        sa.Column("component", sa.String(40)),
        sa.Column("parameter", sa.String(80), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("value_norm", sa.Float, nullable=False),
        sa.Column("unit_norm", sa.String(20), nullable=False),
        sa.Column("condition", sa.Text),
        sa.Column("doc_id", sa.String(200), nullable=False),
        sa.Column("doc_version", sa.Integer, nullable=False),
        sa.Column("locator", sa.JSON, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("source_text", sa.Text, nullable=False),
    )
    op.create_index("ix_parameters_system", "parameters", ["system"])
    op.create_index("ix_parameters_parameter", "parameters", ["parameter"])
    op.create_index("ix_parameters_doc_id", "parameters", ["doc_id"])


def downgrade() -> None:
    op.drop_table("parameters")
