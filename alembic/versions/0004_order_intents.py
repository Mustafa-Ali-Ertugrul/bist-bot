"""Add durable order intent outbox.

Revision ID: 0004_order_intents
Revises: 0003_user_role_default
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_order_intents"
down_revision: str | Sequence[str] | None = "0003_user_role_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "order_intents" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "order_intents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("active_key", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("broker_order_id", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
        sa.UniqueConstraint("active_key"),
    )
    op.create_index("ix_order_intents_client_id", "order_intents", ["client_id"], unique=True)
    op.create_index("ix_order_intents_active_key", "order_intents", ["active_key"], unique=True)
    op.create_index("ix_order_intents_ticker", "order_intents", ["ticker"])
    op.create_index("ix_order_intents_status", "order_intents", ["status"])
    op.create_index("ix_order_intents_broker_order_id", "order_intents", ["broker_order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_intents_broker_order_id", table_name="order_intents")
    op.drop_index("ix_order_intents_status", table_name="order_intents")
    op.drop_index("ix_order_intents_ticker", table_name="order_intents")
    op.drop_index("ix_order_intents_client_id", table_name="order_intents")
    op.drop_index("ix_order_intents_active_key", table_name="order_intents")
    op.drop_table("order_intents")
