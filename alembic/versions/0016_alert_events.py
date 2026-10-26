"""Faz P3.3: in-app alert event history.

Revision ID: 0016_alert_events
Revises: 0015_kap_actions
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_alert_events"
down_revision: str | Sequence[str] | None = "0015_kap_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "user_alert_events" in tables:
        return
    op.create_table(
        "user_alert_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "as_of", "ref", name="uq_user_alert_events_user_day_ref"),
    )
    op.create_index("ix_user_alert_events_user_id", "user_alert_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_alert_events_user_id", table_name="user_alert_events")
    op.drop_table("user_alert_events")
