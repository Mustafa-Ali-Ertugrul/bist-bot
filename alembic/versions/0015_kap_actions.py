"""Faz A: KAP disclosures and corporate actions.

Revision ID: 0015_kap_actions
Revises: 0014_legal_acceptances
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_kap_actions"
down_revision: str | Sequence[str] | None = "0014_legal_acceptances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "kap_disclosures" not in tables:
        op.create_table(
            "kap_disclosures",
            sa.Column("disclosure_index", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("ticker", sa.String(), nullable=True),
            sa.Column("company_title", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("disclosure_class", sa.String(), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=False),
            sa.Column("published_date", sa.Date(), nullable=False),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_kap_disclosures_ticker_date", "kap_disclosures", ["ticker", "published_date"]
        )
        op.create_index("ix_kap_disclosures_published_date", "kap_disclosures", ["published_date"])
    if "corporate_actions" not in tables:
        op.create_table(
            "corporate_actions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("action_date", sa.Date(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("cash_per_share_tl", sa.Float(), nullable=True),
            sa.Column("cash_ratio_pct", sa.Float(), nullable=True),
            sa.Column("bonus_ratio_pct", sa.Float(), nullable=True),
            sa.Column("rights_ratio_pct", sa.Float(), nullable=True),
            sa.Column("rights_amount_tl", sa.Float(), nullable=True),
            sa.Column("post_capital_tl", sa.Float(), nullable=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("ticker", "action_date", "kind", name="uq_corporate_actions"),
        )
        op.create_index(
            "ix_corporate_actions_ticker_date", "corporate_actions", ["ticker", "action_date"]
        )
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("screen_snapshots")
    }
    if "dividend_yield_pct" not in columns:
        op.add_column(
            "screen_snapshots", sa.Column("dividend_yield_pct", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("screen_snapshots") as batch:
        batch.drop_column("dividend_yield_pct")
    op.drop_index("ix_corporate_actions_ticker_date", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_index("ix_kap_disclosures_published_date", table_name="kap_disclosures")
    op.drop_index("ix_kap_disclosures_ticker_date", table_name="kap_disclosures")
    op.drop_table("kap_disclosures")
