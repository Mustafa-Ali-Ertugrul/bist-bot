"""Tests for Streamlit runtime scan and refresh helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

TR = timezone(timedelta(hours=3))


def test_ensure_initial_data_starts_background_scan_when_no_cache():
    """When no cached signals exist, ensure_initial_data should start a full background scan."""
    mock_db = MagicMock()
    mock_db.get_recent_signals.return_value = []

    mock_session = MagicMock()
    mock_session.signals = []
    mock_session.scan_in_progress = False
    mock_session.scan_error = None
    mock_session._scan_session_key = "test-key"
    mock_session.db = mock_db
    mock_session.get = lambda key, default=None: {
        "signals": [],
        "scan_in_progress": False,
        "scan_error": None,
        "_scan_session_key": "test-key",
        "db": mock_db,
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_scan.st") as mock_st,
        patch("bist_bot.ui.runtime_scan.start_background_scan") as mock_start,
        patch("bist_bot.ui.runtime_scan.apply_pending_scan_result"),
    ):
        mock_st.session_state = mock_session
        mock_start.return_value = True

        from bist_bot.ui.runtime_scan import ensure_initial_data

        ensure_initial_data()

        mock_start.assert_called_once_with(force_clear=False, limited=False)
        assert mock_session.scan_in_progress is True


def test_ensure_initial_data_uses_cached_signals_when_available():
    """When cached signals exist, ensure_initial_data should use them and start full background scan."""
    mock_db = MagicMock()
    mock_db.get_recent_signals.return_value = [
        {"ticker": "THYAO.IS", "signal_type": "AL", "score": 25.0, "price": 100.0}
    ]
    mapped_signals = [MagicMock()]

    mock_session = MagicMock()
    mock_session.signals = []
    mock_session.scan_in_progress = False
    mock_session.scan_error = None
    mock_session._scan_session_key = "test-key"
    mock_session.db = mock_db
    mock_session.get = lambda key, default=None: {
        "signals": [],
        "scan_in_progress": False,
        "scan_error": None,
        "_scan_session_key": "test-key",
        "db": mock_db,
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_scan.st") as mock_st,
        patch("bist_bot.ui.runtime_scan.start_background_scan") as mock_start,
        patch("bist_bot.ui.runtime_scan.apply_pending_scan_result"),
        patch("bist_bot.ui.runtime_data.map_cached_signals", return_value=mapped_signals),
    ):
        mock_st.session_state = mock_session
        mock_start.return_value = True

        from bist_bot.ui.runtime_scan import ensure_initial_data

        ensure_initial_data()

        assert mock_session.signals == mapped_signals
        mock_start.assert_called_once_with(force_clear=False, limited=False)


def test_ensure_initial_data_does_not_start_scan_if_already_running():
    """ensure_initial_data should not start a new scan if one is already in progress."""
    mock_db = MagicMock()

    mock_session = MagicMock()
    mock_session.signals = []
    mock_session.scan_in_progress = True
    mock_session.scan_error = None
    mock_session._scan_session_key = "test-key"
    mock_session.db = mock_db
    mock_session.get = lambda key, default=None: {
        "signals": [],
        "scan_in_progress": True,
        "scan_error": None,
        "_scan_session_key": "test-key",
        "db": mock_db,
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_scan.st") as mock_st,
        patch("bist_bot.ui.runtime_scan.start_background_scan") as mock_start,
        patch("bist_bot.ui.runtime_scan.apply_pending_scan_result"),
    ):
        mock_st.session_state = mock_session
        mock_start.return_value = True

        from bist_bot.ui.runtime_scan import ensure_initial_data

        ensure_initial_data()

        mock_start.assert_not_called()


def test_sync_runtime_feedback_skips_rerun_during_bootstrap():
    """sync_runtime_feedback should not rerun when just_logged_in is True."""
    mock_session = MagicMock()
    mock_session.scan_in_progress = True
    mock_session.scan_error = None
    mock_session.just_logged_in = True
    mock_session.auto_refresh = False
    mock_session.last_scan_time = None
    mock_session.get = lambda key, default=None: {
        "scan_in_progress": True,
        "scan_error": None,
        "just_logged_in": True,
        "auto_refresh": False,
        "last_scan_time": None,
        "scan_started_at": None,
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_refresh.st") as mock_st,
        patch("bist_bot.ui.runtime_refresh.time") as mock_time,
        patch("bist_bot.ui.runtime_refresh.check_scan_timeout", return_value=False),
    ):
        mock_st.session_state = mock_session

        from bist_bot.ui.runtime_refresh import sync_runtime_feedback

        callback = MagicMock()
        sync_runtime_feedback(callback)

        callback.assert_not_called()
        mock_st.rerun.assert_not_called()
        mock_st.caption.assert_not_called()
        mock_time.sleep.assert_not_called()


def test_sync_runtime_feedback_reruns_when_scan_in_progress_after_bootstrap():
    """sync_runtime_feedback should rerun when scan_in_progress is True and just_logged_in is False."""
    mock_session = MagicMock()
    mock_session.scan_in_progress = True
    mock_session.scan_error = None
    mock_session.just_logged_in = False
    mock_session.auto_refresh = False
    mock_session.last_scan_time = None
    mock_session.get = lambda key, default=None: {
        "scan_in_progress": True,
        "scan_error": None,
        "just_logged_in": False,
        "auto_refresh": False,
        "last_scan_time": None,
        "scan_started_at": None,
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_refresh.st") as mock_st,
        patch("bist_bot.ui.runtime_refresh.time") as mock_time,
        patch("bist_bot.ui.runtime_refresh.check_scan_timeout", return_value=False),
    ):
        mock_st.session_state = mock_session

        from bist_bot.ui.runtime_refresh import sync_runtime_feedback

        callback = MagicMock()
        sync_runtime_feedback(callback)

        callback.assert_not_called()
        mock_st.caption.assert_called_once()
        mock_time.sleep.assert_called_once_with(1)
        mock_st.rerun.assert_called_once()


def test_scan_timeout_resets_stale_scan_in_progress():
    """If scan_started_at is older than timeout, scan_in_progress should be reset."""
    from bist_bot.ui import runtime_scan

    old_time = datetime.now(TR) - timedelta(seconds=120)

    class FakeSession:
        def __init__(self):
            self.scan_in_progress = True
            self.scan_started_at = old_time
            self.scan_error = None
            self._scan_session_key = "test-key"

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()

    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "settings") as mock_settings,
        patch.object(runtime_scan, "logger") as mock_logger,
    ):
        mock_settings.STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS = 90

        result = runtime_scan.check_scan_timeout()

        assert result is True
        assert fake.scan_in_progress is False
        assert "tamamlanamadi" in fake.scan_error.lower()
        mock_logger.warning.assert_called_once()


def test_scan_timeout_does_not_trigger_when_within_limit():
    """If scan_started_at is recent, check_scan_timeout should return False."""
    from bist_bot.ui import runtime_scan

    recent_time = datetime.now(TR) - timedelta(seconds=30)

    class FakeSession:
        def __init__(self):
            self.scan_in_progress = True
            self.scan_started_at = recent_time
            self._scan_session_key = "test-key"

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()

    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "settings") as mock_settings,
    ):
        mock_settings.STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS = 90

        result = runtime_scan.check_scan_timeout()

        assert result is False
        assert fake.scan_in_progress is True


def test_start_background_scan_sets_scan_started_at():
    """start_background_scan should record scan_started_at in session state."""
    from bist_bot.ui import runtime_scan

    class FakeSession:
        def __init__(self):
            self._scan_session_key = "test-key"
            self.scan_in_progress = False
            self.scan_error = None
            self.scan_started_at = None
            self.data_fetcher = MagicMock()
            self.engine = MagicMock()
            self.notifier = MagicMock()
            self.db = MagicMock()
            self.last_scan_time = None

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()

    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "threading") as mock_threading,
        patch.object(runtime_scan, "logger"),
        patch.object(runtime_scan, "settings") as mock_settings,
    ):
        mock_settings.WATCHLIST = ["THYAO.IS", "ASELS.IS"]
        mock_settings.STREAMLIT_INITIAL_SCAN_LIMIT = 20
        mock_threading.Thread = MagicMock()

        runtime_scan.start_background_scan(force_clear=False, limited=False)

        assert fake.scan_in_progress is True
        assert fake.scan_started_at is not None
        assert fake.scan_error is None
        mock_threading.Thread.assert_called_once()


def test_background_scan_worker_failure_clears_active_session():
    """If worker raises, the result should contain error and active session should be cleared."""
    from bist_bot.ui import runtime_scan

    class FakeSession:
        def __init__(self):
            self._scan_session_key = "fail-key"
            self.scan_started_at = datetime.now(TR)
            self.data_fetcher = MagicMock()
            self.engine = MagicMock()
            self.notifier = MagicMock()
            self.db = MagicMock()
            self.last_scan_time = None

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()

    mock_fetcher = MagicMock()
    mock_fetcher.fetch_multi_timeframe_all.side_effect = RuntimeError("network error")

    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "threading") as mock_threading,
        patch.object(runtime_scan, "logger"),
        patch.object(runtime_scan, "settings") as mock_settings,
        patch.object(
            runtime_scan,
            "_session_dependencies",
            return_value=(mock_fetcher, MagicMock(), MagicMock(), MagicMock(), None),
        ),
    ):
        mock_settings.WATCHLIST = []
        mock_threading.Thread = MagicMock()

        runtime_scan.start_background_scan(force_clear=False, limited=False)

        call_args = mock_threading.Thread.call_args
        worker_fn = call_args.kwargs["target"]

        worker_fn()

        with runtime_scan.SCAN_LOCK:
            assert "fail-key" not in runtime_scan.ACTIVE_SCAN_SESSIONS
            pending = runtime_scan.PENDING_SCAN_RESULTS.pop("fail-key", None)
            assert pending is not None
            assert pending.get("error") is not None


def test_start_background_scan_limited_respects_initial_scan_limit():
    """start_background_scan(limited=True) should slice watchlist to STREAMLIT_INITIAL_SCAN_LIMIT."""
    from bist_bot.ui import runtime_scan

    class FakeSession:
        def __init__(self):
            self._scan_session_key = "limit-key"
            self.scan_in_progress = False
            self.scan_error = None
            self.scan_started_at = None
            self.data_fetcher = MagicMock()
            self.engine = MagicMock()
            self.notifier = MagicMock()
            self.db = MagicMock()
            self.last_scan_time = None

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()
    full_watchlist = [f"TICK{i}.IS" for i in range(100)]

    captured_tickers = None

    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "threading") as mock_threading,
        patch.object(runtime_scan, "logger"),
        patch.object(runtime_scan, "settings") as mock_settings,
        patch.object(runtime_scan, "collect_scan_result") as mock_collect,
    ):
        mock_settings.WATCHLIST = full_watchlist
        mock_settings.STREAMLIT_INITIAL_SCAN_LIMIT = 20
        mock_threading.Thread = MagicMock()

        runtime_scan.start_background_scan(force_clear=False, limited=True)

        worker_fn = mock_threading.Thread.call_args.kwargs["target"]
        worker_fn()

        call_args = mock_collect.call_args
        captured_tickers = call_args.kwargs.get("limited_tickers")

    assert captured_tickers is not None
    assert len(captured_tickers) == 20
    assert captured_tickers == full_watchlist[:20]


def test_start_background_scan_unlimited_scans_all_tickers():
    """start_background_scan(limited=False) should pass limited_tickers=None to scan all tickers."""
    from bist_bot.ui import runtime_scan

    class FakeSession:
        def __init__(self):
            self._scan_session_key = "unlimit-key"
            self.scan_in_progress = False
            self.scan_error = None
            self.scan_started_at = None
            self.data_fetcher = MagicMock()
            self.engine = MagicMock()
            self.notifier = MagicMock()
            self.db = MagicMock()
            self.last_scan_time = None

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()
    full_watchlist = [f"TICK{i}.IS" for i in range(100)]

    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "threading") as mock_threading,
        patch.object(runtime_scan, "logger"),
        patch.object(runtime_scan, "settings") as mock_settings,
        patch.object(runtime_scan, "collect_scan_result") as mock_collect,
    ):
        mock_settings.WATCHLIST = full_watchlist
        mock_settings.STREAMLIT_INITIAL_SCAN_LIMIT = 20
        mock_threading.Thread = MagicMock()

        runtime_scan.start_background_scan(force_clear=False, limited=False)

        worker_fn = mock_threading.Thread.call_args.kwargs["target"]
        worker_fn()

        call_args = mock_collect.call_args
        captured_tickers = call_args.kwargs.get("limited_tickers")

    assert captured_tickers is None
