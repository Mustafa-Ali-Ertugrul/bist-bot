"""WP5: runtime index cleanup, entry_time index, sargable daily count, table-name validation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bist_bot.agent.position_manager import PositionManager  # noqa: E402
from bist_bot.config.subsettings import _get_table_name_env  # noqa: E402
from bist_bot.db.database import DatabaseManager  # noqa: E402


@pytest.fixture
def alembic_cfg():
    ini_path = ROOT_DIR / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("dont_mutate_root_logger", "true")
    return cfg


class TestFreshInitializationIndexes:
    def test_entry_time_index_exists(self, tmp_path):
        db_path = str(tmp_path / "entry_time.db")
        manager = DatabaseManager(sqlite_path=db_path)
        insp = sa.inspect(manager.engine)
        indices = {idx["name"] for idx in insp.get_indexes("live_positions")}
        assert "ix_live_positions_entry_time" in indices

    def test_legacy_idx_names_absent_after_init(self, tmp_path):
        db_path = str(tmp_path / "no_legacy.db")
        manager = DatabaseManager(sqlite_path=db_path)
        insp = sa.inspect(manager.engine)

        legacy_names = {
            "idx_orders_state",
            "idx_scan_log_scan_id",
            "idx_live_positions_state",
            "idx_live_positions_ticker",
            "idx_audit_trail_event_type",
            "idx_audit_trail_timestamp",
            "idx_orders_position_id",
        }
        for table in ("orders", "scan_log", "live_positions", "audit_trail"):
            existing = {idx["name"] for idx in insp.get_indexes(table)}
            assert existing.isdisjoint(legacy_names), (
                f"{table} still has legacy index: {existing & legacy_names}"
            )

    def test_signals_idx_preserved(self, tmp_path):
        db_path = str(tmp_path / "signals.db")
        manager = DatabaseManager(sqlite_path=db_path)
        insp = sa.inspect(manager.engine)
        indices = {idx["name"] for idx in insp.get_indexes("signals")}
        assert "idx_signals_created_at" in indices
        assert "idx_signals_ticker_created_at" in indices

    def test_canonical_ix_indexes_present(self, tmp_path):
        db_path = str(tmp_path / "canonical.db")
        manager = DatabaseManager(sqlite_path=db_path)
        insp = sa.inspect(manager.engine)

        expected = {
            "orders": {
                "ix_orders_state",
                "ix_orders_position_id",
                "ix_orders_ticker",
                "ix_orders_broker_order_id",
            },
            "scan_log": {"ix_scan_log_scan_id", "ix_scan_log_timestamp"},
            "live_positions": {
                "ix_live_positions_state",
                "ix_live_positions_ticker",
                "ix_live_positions_entry_time",
            },
            "audit_trail": {"ix_audit_trail_timestamp", "ix_audit_trail_event_type"},
        }
        for table, names in expected.items():
            existing = {idx["name"] for idx in insp.get_indexes(table)}
            missing = names - existing
            assert not missing, f"{table} missing indexes: {missing}"


class TestLegacyCleanupPath:
    def test_legacy_indexes_dropped_on_reinit(self, tmp_path):
        """Insert legacy idx_* names manually, then init a second manager — they must vanish."""
        db_path = str(tmp_path / "cleanup.db")
        # First manager creates canonical schema
        m1 = DatabaseManager(sqlite_path=db_path)
        # Seed legacy duplicates directly via raw SQL
        with m1.engine.begin() as conn:
            for sql in (
                "CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state)",
                "CREATE INDEX IF NOT EXISTS idx_scan_log_scan_id ON scan_log(scan_id)",
                "CREATE INDEX IF NOT EXISTS idx_live_positions_state ON live_positions(state)",
                "CREATE INDEX IF NOT EXISTS idx_live_positions_ticker ON live_positions(ticker)",
                "CREATE INDEX IF NOT EXISTS idx_audit_trail_event_type ON audit_trail(event_type)",
                "CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp ON audit_trail(timestamp DESC)",
                "CREATE INDEX IF NOT EXISTS idx_orders_position_id ON orders(position_id)",
            ):
                conn.execute(sa.text(sql))
        m1.engine.dispose()

        # Second manager re-runs migrations; legacy idx_* should be gone
        m2 = DatabaseManager(sqlite_path=db_path)
        insp = sa.inspect(m2.engine)
        legacy_names = {
            "idx_orders_state",
            "idx_scan_log_scan_id",
            "idx_live_positions_state",
            "idx_live_positions_ticker",
            "idx_audit_trail_event_type",
            "idx_audit_trail_timestamp",
            "idx_orders_position_id",
        }
        for table in ("orders", "scan_log", "live_positions", "audit_trail"):
            existing = {idx["name"] for idx in insp.get_indexes(table)}
            assert existing.isdisjoint(legacy_names), (
                f"{table} still has legacy index after cleanup: {existing & legacy_names}"
            )
        # Canonical ix_* remain
        assert "ix_live_positions_entry_time" in {
            idx["name"] for idx in insp.get_indexes("live_positions")
        }
        m2.engine.dispose()


class TestDailyTradeCountSargable:
    def _make_pm(self, tmp_path: Path) -> PositionManager:
        manager = DatabaseManager(sqlite_path=str(tmp_path / "daily_count.db"))
        fake_db = type("FakeDB", (), {"manager": manager})()
        fake_settings = type("FakeSettings", (), {"agent": type("A", (), {})()})()
        return PositionManager(fake_db, fake_settings)

    def test_counts_only_today(self, tmp_path):
        pm = self._make_pm(tmp_path)
        today = datetime.now(UTC)
        yesterday = today - timedelta(days=1)
        with pm.db.manager.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO live_positions "
                    "(ticker, side, entry_order_id, entry_price, quantity, entry_time, "
                    "stop_loss, target_price, state, signal_type, signal_score, fees_paid, created_at, updated_at) "
                    "VALUES (:ticker, :side, :eid, :ep, :qty, :et, :sl, :tp, :st, :sig, :ss, :fees, :ca, :ua)"
                ),
                {
                    "ticker": "THYAO.IS",
                    "side": "LONG",
                    "eid": 1,
                    "ep": 100.0,
                    "qty": 10.0,
                    "et": today,
                    "sl": 90.0,
                    "tp": 110.0,
                    "st": "ENTRY_ORDERED",
                    "sig": "STRONG_BUY",
                    "ss": 80.0,
                    "fees": 0.0,
                    "ca": today,
                    "ua": today,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO live_positions "
                    "(ticker, side, entry_order_id, entry_price, quantity, entry_time, "
                    "stop_loss, target_price, state, signal_type, signal_score, fees_paid, created_at, updated_at) "
                    "VALUES (:ticker, :side, :eid, :ep, :qty, :et, :sl, :tp, :st, :sig, :ss, :fees, :ca, :ua)"
                ),
                {
                    "ticker": "ASELS.IS",
                    "side": "LONG",
                    "eid": 2,
                    "ep": 50.0,
                    "qty": 5.0,
                    "et": yesterday,
                    "sl": 45.0,
                    "tp": 55.0,
                    "st": "ENTRY_ORDERED",
                    "sig": "BUY",
                    "ss": 60.0,
                    "fees": 0.0,
                    "ca": yesterday,
                    "ua": yesterday,
                },
            )
        assert pm.get_daily_trade_count() == 1

    def test_empty_table_returns_zero(self, tmp_path):
        pm = self._make_pm(tmp_path)
        assert pm.get_daily_trade_count() == 0


class TestTableNameValidation:
    def test_valid_names_pass(self, monkeypatch: pytest.MonkeyPatch):
        for env_val in ("paper_trades", "my_table_123"):
            monkeypatch.setenv("PAPER_TRADES_TABLE", env_val)
            assert _get_table_name_env("PAPER_TRADES_TABLE", "paper_trades") == env_val
        monkeypatch.delenv("PAPER_TRADES_TABLE", raising=False)

    def test_invalid_names_raise_valueerror(self, monkeypatch: pytest.MonkeyPatch):
        invalid = ["paper_trades;DROP", "123x", "paper-trades"]
        for val in invalid:
            monkeypatch.setenv("PAPER_TRADES_TABLE", val)
            with pytest.raises(ValueError, match="Invalid SQL table name"):
                _get_table_name_env("PAPER_TRADES_TABLE", "paper_trades")
        monkeypatch.delenv("PAPER_TRADES_TABLE", raising=False)

    def test_defaults_to_paper_trades_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PAPER_TRADES_TABLE", raising=False)
        assert _get_table_name_env("PAPER_TRADES_TABLE") == "paper_trades"

    def test_default_value_is_validated(self, monkeypatch: pytest.MonkeyPatch):
        """Default 'paper_trades' must pass validation."""
        monkeypatch.delenv("PAPER_TRADES_TABLE", raising=False)
        # No error should be raised
        result = _get_table_name_env("PAPER_TRADES_TABLE", "paper_trades")
        assert result == "paper_trades"


class TestAlembicMigration:
    def test_upgrade_adds_entry_time_index(self, alembic_cfg, tmp_path):
        db_file = tmp_path / "wp5_alembic.db"
        db_url = f"sqlite:///{db_file.as_posix()}"
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(alembic_cfg, "head")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            indices = {idx["name"] for idx in insp.get_indexes("live_positions")}
            assert "ix_live_positions_entry_time" in indices

    def test_downgrade_removes_entry_time_index(self, alembic_cfg, tmp_path):
        db_file = tmp_path / "wp5_downgrade.db"
        db_url = f"sqlite:///{db_file.as_posix()}"
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(alembic_cfg, "head")
        command.downgrade(alembic_cfg, "0006_subscription_system")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            indices = {idx["name"] for idx in insp.get_indexes("live_positions")}
            assert "ix_live_positions_entry_time" not in indices

    def test_upgrade_drops_legacy_idx_names(self, alembic_cfg, tmp_path):
        db_file = tmp_path / "wp5_legacy.db"
        db_url = f"sqlite:///{db_file.as_posix()}"
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(alembic_cfg, "head")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            legacy = {
                "idx_orders_state",
                "idx_scan_log_scan_id",
                "idx_live_positions_state",
                "idx_live_positions_ticker",
                "idx_audit_trail_event_type",
                "idx_audit_trail_timestamp",
                "idx_orders_position_id",
            }
            for table in ("orders", "scan_log", "live_positions", "audit_trail"):
                existing = {idx["name"] for idx in insp.get_indexes(table)}
                assert existing.isdisjoint(legacy), f"{table} has legacy: {existing & legacy}"
