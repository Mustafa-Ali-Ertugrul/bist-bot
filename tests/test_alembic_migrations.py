from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


@pytest.fixture
def alembic_cfg():
    repo_root = Path(__file__).resolve().parents[1]
    ini_path = repo_root / "alembic.ini"
    cfg = Config(str(ini_path))
    # Silence alembic config logger in tests to prevent clobbering root log handlers
    cfg.set_main_option("dont_mutate_root_logger", "true")
    return cfg


def test_alembic_fresh_upgrade_and_downgrade(alembic_cfg, tmp_path):
    """Test 0001 -> 0002 upgrade, downgrade, and re-upgrade on fresh database."""
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Upgrade to head
    command.upgrade(alembic_cfg, "head")

    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        tables = set(insp.get_table_names())
        assert "signals" in tables
        assert "trade_ledger" in tables
        assert "order_intents" in tables
        assert "users" in tables

        signal_cols = {col["name"] for col in insp.get_columns("signals")}
        assert "score_breakdown" in signal_cols
        assert "outcome_source" in signal_cols
        assert "backfilled_at" in signal_cols

    # 2. Downgrade to 0001
    command.downgrade(alembic_cfg, "0001_initial_schema")
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        tables = set(insp.get_table_names())
        assert "trade_ledger" not in tables
        assert "order_intents" not in tables
        signal_cols = {col["name"] for col in insp.get_columns("signals")}
        assert "score_breakdown" not in signal_cols

    # 3. Re-upgrade to head (idempotency & clean reapplying)
    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        tables = set(insp.get_table_names())
        assert "trade_ledger" in tables
        assert "order_intents" in tables


def test_alembic_idempotent_on_existing_app_schema(alembic_cfg, tmp_path):
    """Test that 0002 safely skips objects if app runtime already created them."""
    from bist_bot.db.database import Base

    db_file = tmp_path / "existing_app.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    engine = sa.create_engine(db_url)

    # Simulate app having already created tables via Base.metadata.create_all
    Base.metadata.create_all(engine)

    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    # Stamp as 0001 first
    command.stamp(alembic_cfg, "0001_initial_schema")

    # Now run upgrade head (0002) - should not crash or duplicate
    command.upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        insp = sa.inspect(conn)
        tables = set(insp.get_table_names())
        assert "trade_ledger" in tables
        assert "order_intents" in tables
