"""Add subscription columns to users and create payment_requests table.

Revision ID: 0006_subscription_system
Revises: 0005_reconcile_accounting
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "0006_subscription_system"
down_revision: str | Sequence[str] | None = "0005_reconcile_accounting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    now_utc = datetime.now(UTC)
    trial_default_expiry = now_utc + timedelta(hours=24)

    if "users" in tables:
        columns = {c["name"] for c in insp.get_columns("users")}
        indexes = {i["name"] for i in insp.get_indexes("users")}
        with op.batch_alter_table("users") as batch_op:
            if "plan" not in columns:
                batch_op.add_column(
                    sa.Column("plan", sa.String(), nullable=False, server_default="trial")
                )
            if "plan_expires_at" not in columns:
                batch_op.add_column(sa.Column("plan_expires_at", sa.DateTime(), nullable=True))
            if "trial_ends_at" not in columns:
                batch_op.add_column(sa.Column("trial_ends_at", sa.DateTime(), nullable=True))
            if "google_id" not in columns:
                batch_op.add_column(sa.Column("google_id", sa.String(), nullable=True))
            if "ix_users_google_id" not in indexes:
                batch_op.create_index("ix_users_google_id", ["google_id"], unique=True)

        # Seed existing users with a fresh 24h trial from migration timestamp if not set
        op.execute(
            sa.text(
                "UPDATE users SET "
                f"plan = 'trial', "
                f"plan_expires_at = '{trial_default_expiry.strftime('%Y-%m-%d %H:%M:%S')}', "
                f"trial_ends_at = '{trial_default_expiry.strftime('%Y-%m-%d %H:%M:%S')}' "
                "WHERE plan_expires_at IS NULL"
            )
        )

    if "payment_requests" not in tables:
        op.create_table(
            "payment_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True
            ),
            sa.Column("plan", sa.String(), nullable=False),
            sa.Column("amount_try", sa.Integer(), nullable=False),
            sa.Column("reference", sa.String(), nullable=False, index=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending", index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "payment_requests" in tables:
        op.drop_table("payment_requests")

    if "users" in tables:
        indexes = {i["name"] for i in insp.get_indexes("users")}
        columns = {c["name"] for c in insp.get_columns("users")}
        with op.batch_alter_table("users") as batch_op:
            if "ix_users_google_id" in indexes:
                batch_op.drop_index("ix_users_google_id")
            for col in ("google_id", "trial_ends_at", "plan_expires_at", "plan"):
                if col in columns:
                    batch_op.drop_column(col)
