"""Faz 2 scan results: one row per (screen, session, ticker).

Revision ID: 0010_scan_results
Revises: 0009_market_data
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_scan_results"
down_revision: str | Sequence[str] | None = "0009_market_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "scan_results" not in set(inspector.get_table_names()):
        op.create_table(
            "scan_results",
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("detail", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("scan_id", "as_of", "ticker", name="pk_scan_results"),
        )
    indexes = {index["name"] for index in inspector.get_indexes("scan_results")}
    if "ix_scan_results_as_of" not in indexes:
        op.create_index("ix_scan_results_as_of", "scan_results", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_scan_results_as_of", table_name="scan_results")
    op.drop_table("scan_results")
