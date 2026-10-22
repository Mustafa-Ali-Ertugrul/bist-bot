"""Faz 6: Telegram links, alerts, saved screens and digest idempotency.

Revision ID: 0013_user_alerts
Revises: 0012_user_portfolio
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_alerts"
down_revision: str | Sequence[str] | None = "0012_user_portfolio"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "user_telegram_links" not in tables:
        op.create_table(
            "user_telegram_links",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("chat_id", sa.String(), nullable=False, unique=True),
            sa.Column("username", sa.String(), nullable=True),
            sa.Column("linked_at", sa.DateTime(), nullable=False),
        )

    if "user_telegram_link_tokens" not in tables:
        op.create_table(
            "user_telegram_link_tokens",
            sa.Column("token_hash", sa.String(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if "user_alerts" not in tables:
        op.create_table(
            "user_alerts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("target", sa.String(), nullable=False),
            sa.Column("op", sa.String(), nullable=True),
            sa.Column("threshold", sa.Float(), nullable=True),
            sa.Column("only_watchlist", sa.Boolean(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_user_alerts_user_id", "user_alerts", ["user_id"])

    if "user_saved_screens" not in tables:
        op.create_table(
            "user_saved_screens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "name", name="uq_user_saved_screens_user_name"),
        )

    if "user_digest_log" not in tables:
        op.create_table(
            "user_digest_log",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("as_of", sa.Date(), primary_key=True),
            sa.Column("sent_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("user_digest_log")
    op.drop_table("user_saved_screens")
    op.drop_index("ix_user_alerts_user_id", table_name="user_alerts")
    op.drop_table("user_alerts")
    op.drop_table("user_telegram_link_tokens")
    op.drop_table("user_telegram_links")
