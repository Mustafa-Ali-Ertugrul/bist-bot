"""Faz 4 screener: daily per-symbol metrics.

Revision ID: 0011_screen_snapshots
Revises: 0010_scan_results
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_screen_snapshots"
down_revision: str | Sequence[str] | None = "0010_scan_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "close",
    "change_pct",
    "ret_1m",
    "ret_3m",
    "ret_1y",
    "rsi14",
    "sma50_gap_pct",
    "sma200_gap_pct",
    "from_52w_high_pct",
    "avg_volume_20",
    "market_cap_tl",
    "pe_ttm",
    "pb",
    "net_margin_pct",
    "roe_pct",
    "sales_growth_yoy_pct",
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "screen_snapshots" not in set(inspector.get_table_names()):
        op.create_table(
            "screen_snapshots",
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("close", sa.Float(), nullable=False),
            *[sa.Column(name, sa.Float(), nullable=True) for name in _COLUMNS[1:]],
            sa.Column("fundamentals_period", sa.String(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("ticker", "as_of", name="pk_screen_snapshots"),
        )
    indexes = {index["name"] for index in inspector.get_indexes("screen_snapshots")}
    if "ix_screen_snapshots_as_of" not in indexes:
        op.create_index("ix_screen_snapshots_as_of", "screen_snapshots", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_screen_snapshots_as_of", table_name="screen_snapshots")
    op.drop_table("screen_snapshots")
