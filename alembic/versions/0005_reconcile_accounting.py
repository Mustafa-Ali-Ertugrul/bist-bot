"""Add signal_snapshot and order_db_id to order_intents, add bootstrap_state table.

Revision ID: 0005_reconcile_accounting
Revises: 0004_order_intents
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_reconcile_accounting"
down_revision: str | Sequence[str] | None = "0004_order_intents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "order_intents" in tables:
        columns = {c["name"] for c in insp.get_columns("order_intents")}
        indexes = {i["name"] for i in insp.get_indexes("order_intents")}
        with op.batch_alter_table("order_intents") as batch_op:
            if "signal_snapshot" not in columns:
                batch_op.add_column(sa.Column("signal_snapshot", sa.Text(), nullable=True))
            if "order_db_id" not in columns:
                batch_op.add_column(sa.Column("order_db_id", sa.Integer(), nullable=True))
            if "ix_order_intents_order_db_id" not in indexes:
                batch_op.create_index("ix_order_intents_order_db_id", ["order_db_id"])

    if "bootstrap_state" not in tables:
        op.create_table(
            "bootstrap_state",
            sa.Column("key", sa.String(), primary_key=True, nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "bootstrap_state" in tables:
        op.drop_table("bootstrap_state")

    if "order_intents" in tables:
        columns = {c["name"] for c in insp.get_columns("order_intents")}
        indexes = {i["name"] for i in insp.get_indexes("order_intents")}
        with op.batch_alter_table("order_intents") as batch_op:
            if "ix_order_intents_order_db_id" in indexes:
                batch_op.drop_index("ix_order_intents_order_db_id")
            if "order_db_id" in columns:
                batch_op.drop_column("order_db_id")
            if "signal_snapshot" in columns:
                batch_op.drop_column("signal_snapshot")
