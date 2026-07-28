"""Initial schema: signals, scan_log, paper_trades, orders, users, live_positions, audit.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Core market signal tables
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("position_size", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=True),
        sa.Column("reasons", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("outcome_price", sa.Float(), nullable=True),
        sa.Column("outcome_date", sa.DateTime(), nullable=True),
        sa.Column("profit_pct", sa.Float(), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_ticker", "signals", ["ticker"])
    op.create_index("idx_signals_created_at", "signals", ["created_at"])
    op.create_index("idx_signals_ticker_created_at", "signals", ["ticker", "created_at"])

    op.create_table(
        "scan_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("total_scanned", sa.Integer(), nullable=True),
        sa.Column("signals_generated", sa.Integer(), nullable=True),
        sa.Column("buy_signals", sa.Integer(), nullable=True),
        sa.Column("sell_signals", sa.Integer(), nullable=True),
        sa.Column("actionable", sa.Integer(), nullable=True),
        sa.Column("scan_id", sa.String(), nullable=True),
        # TEXT on both backends; app stores JSON string (portable SQLite/Postgres).
        sa.Column("rejection_breakdown", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_log_scan_id", "scan_log", ["scan_id"])

    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("signal_price", sa.Float(), nullable=False),
        sa.Column("signal_time", sa.DateTime(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("regime", sa.String(), nullable=True),
        sa.Column("filled_at", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("actual_profit_pct", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_date", sa.DateTime(), nullable=True),
        sa.Column("close_reason", sa.String(), nullable=True),
        sa.Column("close_time", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_trades_ticker", "paper_trades", ["ticker"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("broker_order_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("filled_qty", sa.Float(), nullable=False),
        sa.Column("avg_fill_price", sa.Float(), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_ticker", "orders", ["ticker"])
    op.create_index("ix_orders_state", "orders", ["state"])
    op.create_index("ix_orders_broker_order_id", "orders", ["broker_order_id"])
    op.create_index("ix_orders_position_id", "orders", ["position_id"])

    op.create_table(
        "live_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("entry_order_id", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("entry_time", sa.DateTime(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("risk_reward_ratio", sa.Float(), nullable=True),
        sa.Column("position_size_method", sa.String(), nullable=True),
        sa.Column("exit_order_id", sa.Integer(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_time", sa.DateTime(), nullable=True),
        sa.Column("exit_reason", sa.String(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("realized_pnl_pct", sa.Float(), nullable=True),
        sa.Column("fees_paid", sa.Float(), nullable=False),
        sa.Column("settlement_date", sa.DateTime(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("signal_score", sa.Float(), nullable=False),
        sa.Column("regime", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_live_positions_ticker", "live_positions", ["ticker"])
    op.create_index("ix_live_positions_state", "live_positions", ["state"])

    op.create_table(
        "audit_trail",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("agent_state", sa.String(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("trigger_source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_trail_timestamp", "audit_trail", ["timestamp"])
    op.create_index("ix_audit_trail_event_type", "audit_trail", ["event_type"])
    op.create_index("ix_audit_trail_ticker", "audit_trail", ["ticker"])
    op.create_index("ix_audit_trail_position_id", "audit_trail", ["position_id"])


def downgrade() -> None:
    op.drop_table("audit_trail")
    op.drop_table("live_positions")
    op.drop_table("orders")
    op.drop_table("users")
    op.drop_table("app_settings")
    op.drop_table("paper_trades")
    op.drop_table("scan_log")
    op.drop_table("signals")
