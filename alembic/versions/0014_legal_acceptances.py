"""Faz 7: consent records for the legal documents.

Revision ID: 0014_legal_acceptances
Revises: 0013_user_alerts
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_legal_acceptances"
down_revision: str | Sequence[str] | None = "0013_user_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "legal_acceptances" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "legal_acceptances",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("document", sa.String(), primary_key=True),
            sa.Column("version", sa.String(), primary_key=True),
            sa.Column("accepted_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("legal_acceptances")
