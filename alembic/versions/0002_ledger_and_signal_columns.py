"""Add trade_ledger table, signal/paper columns, unique users email index.

Revision ID: 0002_ledger_and_signal_columns
Revises: 0001_initial_schema
Create Date: 2026-09-03

Additive migration bringing early databases (created by 0001) up to the
current models:

- New ``trade_ledger`` table (unified PAPER/SHADOW ledger, Sprint 2).
- New columns: ``signals.score_breakdown``, ``signals.outcome_source``,
  ``signals.backfilled_at``, ``paper_trades.direction``.
- ``users.email``: ensure ``ix_users_email`` is unique, matching the
  models' ``unique=True, index=True`` (uniqueness itself has always been
  enforced by the ``UNIQUE`` constraint from 0001).

Idempotency: the application runtime also converges SQLite databases via
``Base.metadata.create_all`` + legacy PRAGMA migrations, so every step
below is guarded by inspection and skips objects that already exist
(e.g. local ``bist_signals.db`` files or Postgres databases that the app
itself already brought up to date).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_ledger_and_signal_columns"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _existing_indexes(table: str) -> dict[str, dict]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return {}
    return {idx["name"]: idx for idx in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "trade_ledger" not in tables:
        op.create_table(
            "trade_ledger",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("signal_type", sa.String(), nullable=False),
            sa.Column("direction", sa.String(), nullable=False, server_default="long"),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("regime", sa.String(), nullable=True),
            sa.Column("entry_price", sa.Float(), nullable=False),
            sa.Column("entry_time", sa.DateTime(), nullable=False),
            sa.Column("stop_loss", sa.Float(), nullable=True),
            sa.Column("target_price", sa.Float(), nullable=True),
            sa.Column("agreement_ratio", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
            sa.Column("exit_price", sa.Float(), nullable=True),
            sa.Column("exit_time", sa.DateTime(), nullable=True),
            sa.Column("close_reason", sa.String(), nullable=True),
            sa.Column("gross_pnl_pct", sa.Float(), nullable=True),
            sa.Column("net_pnl_pct", sa.Float(), nullable=True),
            sa.Column("paper_trade_id", sa.Integer(), nullable=True),
            sa.Column("signal_id", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_trade_ledger_kind", "trade_ledger", ["kind"])
        op.create_index("ix_trade_ledger_ticker", "trade_ledger", ["ticker"])
        op.create_index("ix_trade_ledger_status", "trade_ledger", ["status"])
        op.create_index("ix_trade_ledger_paper_trade_id", "trade_ledger", ["paper_trade_id"])
        op.create_index("ix_trade_ledger_signal_id", "trade_ledger", ["signal_id"])

    signal_cols = _existing_columns("signals")
    if "score_breakdown" not in signal_cols:
        op.add_column("signals", sa.Column("score_breakdown", sa.Text(), nullable=True))
    if "outcome_source" not in signal_cols:
        op.add_column("signals", sa.Column("outcome_source", sa.String(), nullable=True))
    if "backfilled_at" not in signal_cols:
        op.add_column("signals", sa.Column("backfilled_at", sa.DateTime(), nullable=True))

    if "direction" not in _existing_columns("paper_trades"):
        op.add_column("paper_trades", sa.Column("direction", sa.String(), nullable=True))

    # Align the email index with the models (unique). The UNIQUE constraint
    # from 0001 keeps enforcing uniqueness on every backend.
    email_idx = _existing_indexes("users").get("ix_users_email")
    if email_idx is None:
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    elif not email_idx.get("unique", False):
        op.drop_index("ix_users_email", table_name="users")
        op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    with op.batch_alter_table("paper_trades") as batch_op:
        batch_op.drop_column("direction")
    with op.batch_alter_table("signals") as batch_op:
        batch_op.drop_column("backfilled_at")
        batch_op.drop_column("outcome_source")
        batch_op.drop_column("score_breakdown")

    op.drop_index("ix_trade_ledger_signal_id", table_name="trade_ledger")
    op.drop_index("ix_trade_ledger_paper_trade_id", table_name="trade_ledger")
    op.drop_index("ix_trade_ledger_status", table_name="trade_ledger")
    op.drop_index("ix_trade_ledger_ticker", table_name="trade_ledger")
    op.drop_index("ix_trade_ledger_kind", table_name="trade_ledger")
    op.drop_table("trade_ledger")
