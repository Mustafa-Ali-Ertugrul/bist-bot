"""Add missing runtime index and clean up legacy idx_* duplicates.

Revision ID: 0007_missing_runtime_indexes
Revises: 0006_subscription_system
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_missing_runtime_indexes"
down_revision: str | Sequence[str] | None = "0006_subscription_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # entry_time had no index until this migration; ORM create_all now emits it,
    # but existing databases need the explicit creation here. Drop first for
    # idempotency when create_all has already created it (e.g. stamp+upgrade
    # test paths).
    op.execute("DROP INDEX IF EXISTS ix_live_positions_entry_time")
    op.create_index("ix_live_positions_entry_time", "live_positions", ["entry_time"])

    # Drop redundant idx_* names that were created at runtime by the legacy
    # _create_indexes / _migrate_agent_schema paths. Wrapped individually so a
    # missing index on a given backend does not abort the batch.
    for idx in (
        "idx_orders_state",
        "idx_scan_log_scan_id",
        "idx_live_positions_state",
        "idx_live_positions_ticker",
        "idx_audit_trail_event_type",
        "idx_audit_trail_timestamp",
        "idx_orders_position_id",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")


def downgrade() -> None:
    op.drop_index("ix_live_positions_entry_time", table_name="live_positions")
    # Note: we do NOT recreate the redundant legacy idx_* indexes — they are
    # intentionally replaced by the canonical ix_* counterparts.
