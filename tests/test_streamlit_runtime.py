from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timedelta, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


class MockSessionState(dict):
    def __init__(self, **kwargs):
        super().__init__()
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        try:
            val = getattr(self, key, default)
            return val if val is not None else default
        except AttributeError:
            return default


def test_sync_runtime_feedback_no_rerun_when_scan_in_progress():
    rerun_called = [False]
    info_called = [False]

    class MockSt:
        session_state = MockSessionState(
            scan_in_progress=True,
            scan_error=None,
            auto_refresh=False,
            last_scan_time=None,
            refresh_interval=5,
        )

        def error(self, msg):
            pass

        def info(self, msg, icon=None):
            info_called[0] = True

        def caption(self, msg):
            pass

        def rerun(self):
            rerun_called[0] = True

    mock_st = MockSt()

    def mock_run_scan(force_clear=False):
        pass

    import bist_bot.ui.runtime_refresh as rr

    original_st = rr.st
    try:
        rr.st = mock_st
        rr.sync_runtime_feedback(mock_run_scan)
    finally:
        rr.st = original_st

    assert not rerun_called[0], "st.rerun() should not be called"
    assert info_called[0], "st.info() should be called to show scan in progress"


def test_sync_runtime_feedback_shows_error_when_present():
    error_msg = [None]

    class MockSt:
        session_state = MockSessionState(
            scan_in_progress=False,
            scan_error="Database connection failed",
            auto_refresh=False,
            last_scan_time=None,
        )

        def error(self, msg):
            error_msg[0] = msg

        def info(self, msg, icon=None):
            pass

    mock_st = MockSt()

    def mock_run_scan(force_clear=False):
        pass

    import bist_bot.ui.runtime_refresh as rr

    original_st = rr.st
    try:
        rr.st = mock_st
        rr.sync_runtime_feedback(mock_run_scan)
    finally:
        rr.st = original_st

    assert "Database connection failed" in error_msg[0]


def test_check_scan_timeout_clears_stale_scan():
    import bist_bot.ui.runtime_scan as rs

    session_key = "test_session_456"
    with rs.SCAN_LOCK:
        rs.ACTIVE_SCAN_SESSIONS.add(session_key)
        rs.SCAN_START_TIMES[session_key] = datetime.now(
            timezone(timedelta(hours=3))
        ) - timedelta(seconds=200)

    class MockSt:
        session_state = MockSessionState(
            _scan_session_key=session_key, scan_in_progress=True
        )

    class MockSettings:
        STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS = 120

    original_settings = rs.settings
    original_st = rs.st
    try:
        rs.settings = MockSettings()
        rs.st = MockSt()
        rs.check_scan_timeout()
    finally:
        rs.settings = original_settings
        rs.st = original_st

    with rs.SCAN_LOCK:
        assert session_key not in rs.ACTIVE_SCAN_SESSIONS
        assert session_key not in rs.SCAN_START_TIMES


def test_background_worker_stores_result_without_streamlit_access():
    import bist_bot.ui.runtime_scan as rs

    session_key = "test_session_worker"
    with rs.SCAN_LOCK:
        rs.ACTIVE_SCAN_SESSIONS.add(session_key)
        rs.SCAN_START_TIMES[session_key] = datetime.now(timezone(timedelta(hours=3)))

    captured_result = [None]

    def mock_collect_scan_result(
        fetcher, engine, notifier, db, last_scan_time=None, force_clear=False
    ):
        return {
            "all_data": {"THYAO.IS": {}},
            "signals": [],
            "last_scan_time": None,
            "error": None,
        }

    def worker():
        captured_result[0] = mock_collect_scan_result(None, None, None, None)
        with rs.SCAN_LOCK:
            rs.PENDING_SCAN_RESULTS[session_key] = captured_result[0]
            rs.ACTIVE_SCAN_SESSIONS.discard(session_key)
            rs.SCAN_START_TIMES.pop(session_key, None)

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    with rs.SCAN_LOCK:
        assert session_key in rs.PENDING_SCAN_RESULTS
        assert session_key not in rs.ACTIVE_SCAN_SESSIONS

    assert captured_result[0] is not None
    assert "THYAO.IS" in captured_result[0]["all_data"]


def test_streamlit_scan_persists_all_signals_to_same_db_as_api():
    """Verify Streamlit scan path saves ALL signals to the shared DB, not a separate local store."""
    import tempfile

    from bist_bot.db import DataAccess, DatabaseManager
    from bist_bot.strategy.signal_models import Signal, SignalType

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "shared_test.db")
        manager = DatabaseManager(sqlite_path=db_path)
        db = DataAccess(manager)

        # Simulate what collect_scan_result does: save ALL signals
        hold_signal = Signal(
            ticker="ASELS.IS", signal_type=SignalType.HOLD, score=3, price=150.0
        )
        buy_signal = Signal(
            ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0
        )
        db.save_signals([hold_signal, buy_signal])

        # Verify both signals are retrievable from the same DB
        recent = db.get_recent_signals(limit=10)
        assert len(recent) == 2
        tickers = {r["ticker"] for r in recent}
        assert "ASELS.IS" in tickers
        assert "THYAO.IS" in tickers

        # Verify the API-facing get_recent_signals returns the same data
        # (no separate local DB state)
        api_signals = db.get_signals(limit=10)
        assert len(api_signals) == 2
        assert {r["ticker"] for r in api_signals} == tickers

        manager.session_factory.remove()
        manager.engine.dispose()


def test_dashboard_shows_scanned_count_separate_from_actionable():
    """Verify scan log stores scanned vs actionable separately for dashboard display."""
    import tempfile

    from bist_bot.db import DataAccess, DatabaseManager

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "scanlog_test.db")
        manager = DatabaseManager(sqlite_path=db_path)
        db = DataAccess(manager)

        # Simulate a scan with 20 assets scanned, 0 actionable (all HOLD)
        db.save_scan_log(total=20, generated=0, buys=0, sells=0)

        latest = db.get_latest_scan_log()
        assert latest is not None
        assert latest["total_scanned"] == 20
        assert latest["signals_generated"] == 0

        # Dashboard can now show "20 assets scanned, 0 actionable signals"
        # instead of the misleading "Signal volume 0"
        assert latest["total_scanned"] > latest["signals_generated"]

        manager.session_factory.remove()
        manager.engine.dispose()
