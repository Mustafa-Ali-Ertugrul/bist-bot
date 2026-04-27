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
            refresh_interval=5
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

    assert not rerun_called[0], 'st.rerun() should not be called'
    assert info_called[0], 'st.info() should be called to show scan in progress'


def test_sync_runtime_feedback_shows_error_when_present():
    error_msg = [None]

    class MockSt:
        session_state = MockSessionState(
            scan_in_progress=False,
            scan_error='Database connection failed',
            auto_refresh=False,
            last_scan_time=None
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

    assert 'Database connection failed' in error_msg[0]


def test_check_scan_timeout_clears_stale_scan():
    import bist_bot.ui.runtime_scan as rs

    session_key = 'test_session_456'
    with rs.SCAN_LOCK:
        rs.ACTIVE_SCAN_SESSIONS.add(session_key)
        rs.SCAN_START_TIMES[session_key] = datetime.now(timezone(timedelta(hours=3))) - timedelta(seconds=200)

    class MockSt:
        session_state = MockSessionState(
            _scan_session_key=session_key,
            scan_in_progress=True
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

    session_key = 'test_session_worker'
    with rs.SCAN_LOCK:
        rs.ACTIVE_SCAN_SESSIONS.add(session_key)
        rs.SCAN_START_TIMES[session_key] = datetime.now(timezone(timedelta(hours=3)))

    captured_result = [None]

    def mock_collect_scan_result(fetcher, engine, notifier, db, last_scan_time=None, force_clear=False):
        return {
            'all_data': {'THYAO.IS': {}},
            'signals': [],
            'last_scan_time': None,
            'error': None,
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
    assert 'THYAO.IS' in captured_result[0]['all_data']
