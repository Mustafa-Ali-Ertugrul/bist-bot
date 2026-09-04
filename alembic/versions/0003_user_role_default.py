"""Default new users to the least-privileged role.

Revision ID: 0003_user_role_default
Revises: 0002_ledger_and_signal_columns
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_user_role_default"
down_revision: str | Sequence[str] | None = "0002_ledger_and_signal_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(),
            nullable=False,
            server_default="user",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(),
            nullable=False,
            server_default=None,
        )
