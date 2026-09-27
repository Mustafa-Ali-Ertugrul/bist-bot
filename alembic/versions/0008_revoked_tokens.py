"""Create revoked_tokens table for durable refresh-token revocation.

Revision ID: 0008_revoked_tokens
Revises: 0007_missing_runtime_indexes
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_revoked_tokens"
down_revision: str | Sequence[str] | None = "0007_missing_runtime_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ORM create_all may already have created the table at app startup.
    if "revoked_tokens" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(), primary_key=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
