"""Faz 1 market data: instruments, daily_bars, fundamentals.

Revision ID: 0009_market_data
Revises: 0007_missing_runtime_indexes
Create Date: 2026-10-21

Note: 0008_revoked_tokens exists in HEAD but was removed from the working tree
(revocation moved back to the in-memory store), so this revision chains off
0007. If that migration ever returns, re-chain this file onto it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_market_data"
down_revision: str | Sequence[str] | None = "0007_missing_runtime_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    # create_all may have created the tables at app startup already.
    if "instruments" not in tables:
        op.create_table(
            "instruments",
            sa.Column("code", sa.String(), primary_key=True),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("sector", sa.String(), nullable=True),
            sa.Column("market", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("first_seen", sa.DateTime(), nullable=False),
            sa.Column("last_seen", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("ticker", name="instruments_ticker_key"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("instruments")}
    if "ix_instruments_sector" not in existing_indexes:
        op.create_index("ix_instruments_sector", "instruments", ["sector"])
    if "ix_instruments_is_active" not in existing_indexes:
        op.create_index("ix_instruments_is_active", "instruments", ["is_active"])

    if "daily_bars" not in tables:
        op.create_table(
            "daily_bars",
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("open", sa.Float(), nullable=True),
            sa.Column("high", sa.Float(), nullable=True),
            sa.Column("low", sa.Float(), nullable=True),
            sa.Column("close", sa.Float(), nullable=False),
            sa.Column("close_raw", sa.Float(), nullable=True),
            sa.Column("volume_tl", sa.Float(), nullable=True),
            sa.Column("market_cap_tl", sa.Float(), nullable=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("ticker", "date", name="pk_daily_bars"),
        )
    daily_indexes = {index["name"] for index in inspector.get_indexes("daily_bars")}
    if "ix_daily_bars_date" not in daily_indexes:
        op.create_index("ix_daily_bars_date", "daily_bars", ["date"])

    if "fundamentals" not in tables:
        op.create_table(
            "fundamentals",
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("period", sa.String(), nullable=False),
            sa.Column("item_code", sa.String(), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("ticker", "period", "item_code", name="pk_fundamentals"),
        )
    fundamental_indexes = {index["name"] for index in inspector.get_indexes("fundamentals")}
    if "ix_fundamentals_period" not in fundamental_indexes:
        op.create_index("ix_fundamentals_period", "fundamentals", ["period"])


def downgrade() -> None:
    op.drop_index("ix_fundamentals_period", table_name="fundamentals")
    op.drop_table("fundamentals")
    op.drop_index("ix_daily_bars_date", table_name="daily_bars")
    op.drop_table("daily_bars")
    op.drop_index("ix_instruments_is_active", table_name="instruments")
    op.drop_index("ix_instruments_sector", table_name="instruments")
    op.drop_table("instruments")
