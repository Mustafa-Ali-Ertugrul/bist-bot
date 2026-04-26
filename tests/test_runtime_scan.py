"""Tests for Streamlit runtime scan and refresh helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_ensure_initial_data_starts_background_scan_when_no_cache():
    """When no cached signals exist, ensure_initial_data should start a background scan, not block."""
    mock_db = MagicMock()
    mock_db.get_recent_signals.return_value = []

    mock_session = MagicMock()
    mock_session.signals = []
    mock_session.scan_in_progress = False
    mock_session.scan_error = None
    mock_session._scan_session_key = "test-key"
    mock_session.db = mock_db

    with (
        patch("bist_bot.ui.runtime_scan.st") as mock_st,
        patch("bist_bot.ui.runtime_scan.start_background_scan") as mock_start,
        patch("bist_bot.ui.runtime_scan.apply_pending_scan_result"),
    ):
        mock_st.session_state = mock_session
        mock_start.return_value = True

        from bist_bot.ui.runtime_scan import ensure_initial_data

        ensure_initial_data()

        mock_start.assert_called_once_with(force_clear=False)
        assert mock_session.scan_in_progress is True
        mock_st.info.assert_called_once()


def test_ensure_initial_data_uses_cached_signals_when_available():
    """When cached signals exist, ensure_initial_data should use them and start background scan."""
    mock_db = MagicMock()
    mock_db.get_recent_signals.return_value = [
        {"ticker": "THYAO.IS", "signal_type": "AL", "score": 25.0, "price": 100.0}
    ]

    mock_session = MagicMock()
    mock_session.signals = []
    mock_session.scan_in_progress = False
    mock_session.scan_error = None
    mock_session._scan_session_key = "test-key"
    mock_session.db = mock_db

    with (
        patch("bist_bot.ui.runtime_scan.st") as mock_st,
        patch("bist_bot.ui.runtime_scan.start_background_scan") as mock_start,
        patch("bist_bot.ui.runtime_scan.apply_pending_scan_result"),
        patch("bist_bot.ui.runtime_data.map_cached_signals") as mock_map,
    ):
        mock_st.session_state = mock_session
        mock_start.return_value = True
        mock_map.return_value = [MagicMock()]

        from bist_bot.ui.runtime_scan import ensure_initial_data

        ensure_initial_data()

        assert mock_session.signals == mock_map.return_value
        mock_start.assert_called_once_with(force_clear=False)


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
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_refresh.st") as mock_st,
        patch("bist_bot.ui.runtime_refresh.time") as mock_time,
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
    }.get(key, default)

    with (
        patch("bist_bot.ui.runtime_refresh.st") as mock_st,
        patch("bist_bot.ui.runtime_refresh.time") as mock_time,
    ):
        mock_st.session_state = mock_session

        from bist_bot.ui.runtime_refresh import sync_runtime_feedback

        callback = MagicMock()
        sync_runtime_feedback(callback)

        callback.assert_not_called()
        mock_st.caption.assert_called_once()
        mock_time.sleep.assert_called_once_with(1)
        mock_st.rerun.assert_called_once()
