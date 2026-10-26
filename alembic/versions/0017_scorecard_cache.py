"""Faz P3.4: scorecard result cache.

Revision ID: 0017_scorecard_cache
Revises: 0016_alert_events
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_scorecard_cache"
down_revision: str | Sequence[str] | None = "0016_alert_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "scorecard_cache" in tables:
        return
    op.create_table(
        "scorecard_cache",
        sa.Column("cache_key", sa.String(), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scorecard_cache")
