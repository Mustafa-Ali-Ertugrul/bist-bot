"""Faz 5: personal watchlists, manual portfolios and benchmark series.

Revision ID: 0012_user_portfolio
Revises: 0011_screen_snapshots
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_user_portfolio"
down_revision: str | Sequence[str] | None = "0011_screen_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "user_watchlists" not in tables:
        op.create_table(
            "user_watchlists",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "name", name="uq_user_watchlists_user_name"),
        )
        op.create_index("ix_user_watchlists_user_id", "user_watchlists", ["user_id"])

    if "user_watchlist_items" not in tables:
        op.create_table(
            "user_watchlist_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "watchlist_id",
                sa.Integer(),
                sa.ForeignKey("user_watchlists.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("added_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "watchlist_id", "ticker", name="uq_user_watchlist_items_list_ticker"
            ),
        )
        op.create_index(
            "ix_user_watchlist_items_watchlist_id", "user_watchlist_items", ["watchlist_id"]
        )

    if "user_portfolios" not in tables:
        op.create_table(
            "user_portfolios",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "name", name="uq_user_portfolios_user_name"),
        )
        op.create_index("ix_user_portfolios_user_id", "user_portfolios", ["user_id"])

    if "user_portfolio_transactions" not in tables:
        op.create_table(
            "user_portfolio_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "portfolio_id",
                sa.Integer(),
                sa.ForeignKey("user_portfolios.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("side", sa.String(), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("commission_tl", sa.Float(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_user_portfolio_transactions_portfolio_id",
            "user_portfolio_transactions",
            ["portfolio_id"],
        )
        op.create_index(
            "ix_user_portfolio_transactions_ticker", "user_portfolio_transactions", ["ticker"]
        )

    if "benchmark_bars" not in tables:
        op.create_table(
            "benchmark_bars",
            sa.Column("code", sa.String(), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("code", "date", name="pk_benchmark_bars"),
        )
        op.create_index("ix_benchmark_bars_code_date", "benchmark_bars", ["code", "date"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_bars_code_date", table_name="benchmark_bars")
    op.drop_table("benchmark_bars")
    op.drop_index("ix_user_portfolio_transactions_ticker", table_name="user_portfolio_transactions")
    op.drop_index(
        "ix_user_portfolio_transactions_portfolio_id",
        table_name="user_portfolio_transactions",
    )
    op.drop_table("user_portfolio_transactions")
    op.drop_index("ix_user_portfolios_user_id", table_name="user_portfolios")
    op.drop_table("user_portfolios")
    op.drop_index("ix_user_watchlist_items_watchlist_id", table_name="user_watchlist_items")
    op.drop_table("user_watchlist_items")
    op.drop_index("ix_user_watchlists_user_id", table_name="user_watchlists")
    op.drop_table("user_watchlists")
