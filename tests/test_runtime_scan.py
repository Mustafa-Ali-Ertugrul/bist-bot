"""Tests for Streamlit runtime scan and refresh helpers."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

TR = timezone(timedelta(hours=3))


def test_ensure_initial_data_starts_background_scan_when_no_cache():
    """When no cached signals exist, ensure_initial_data should start a limited background scan."""
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

        mock_start.assert_called_once_with(force_clear=False, limited=True)
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
        assert fake.scan_error is not None
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


def test_collect_scan_result_returns_scan_stats():
    from bist_bot.strategy.signal_models import SignalType
    from bist_bot.ui import runtime_scan

    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object()},
        "ASELS.IS": {"trigger": object()},
    }
    engine = MagicMock()
    hold_signal = MagicMock(signal_type=SignalType.HOLD)
    buy_signal = MagicMock(signal_type=SignalType.BUY)
    engine.scan_all.return_value = [hold_signal, buy_signal]
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 3,
        "by_reason": [{"reason_code": "score_filtered_sideways", "count": 3}],
        "by_stage": [{"stage": "scoring", "count": 3}],
        "scan_id": "scan-ui123",
    }
    notifier = MagicMock()
    db = MagicMock()

    with (
        patch.object(runtime_scan, "check_signals", return_value=None),
        patch.object(runtime_scan, "send_signal_notification"),
    ):
        result = runtime_scan.collect_scan_result(fetcher, engine, notifier, db)

    assert result["scan_stats"] == {"generated": 2, "actionable": 1, "hold": 1}
    db.save_scan_log.assert_called_once_with(
        2,
        2,
        1,
        0,
        1,
        scan_id="scan-ui123",
        rejection_breakdown={
            "total_rejections": 3,
            "by_reason": [{"reason_code": "score_filtered_sideways", "count": 3}],
            "by_stage": [{"stage": "scoring", "count": 3}],
            "scan_id": "scan-ui123",
        },
    )


def test_apply_scan_result_persists_scan_stats():
    from bist_bot.ui import runtime_scan

    fake = SimpleNamespace()
    scan_result = {
        "all_data": {},
        "signals": [],
        "last_scan_time": None,
        "error": None,
        "scan_stats": {"generated": 3, "actionable": 2, "hold": 1},
    }

    with patch.object(runtime_scan.st, "session_state", fake):
        runtime_scan.apply_scan_result(scan_result)

    assert fake.scan_stats == {"generated": 3, "actionable": 2, "hold": 1}


def test_analyze_page_uses_buy_threshold_instead_of_hardcoded_score():
    from bist_bot.ui.pages import analyze_page

    source = inspect.getsource(analyze_page)

    assert "settings.BUY_THRESHOLD" in source
    assert "signal_score >= 10" not in source


def test_sidebar_navigation_uses_streamlit_widget_not_page_reload_links():
    from bist_bot.ui.components import app_shell

    source = inspect.getsource(app_shell.render_sidebar_nav)

    assert "st.radio" in source
    assert "href='?page=" not in source
    assert 'href="?page=' not in source
    assert "_sidebar_active_page" in source
    assert "page:" in source


def test_portfolio_page_uses_settings_thresholds_and_excludes_hold_fallback():
    from bist_bot.ui.pages import portfolio_page

    source = inspect.getsource(portfolio_page)

    assert "settings.STRONG_BUY_THRESHOLD" in source
    assert "settings.BUY_THRESHOLD" in source
    assert "SignalType.HOLD" in source


def test_overview_page_uses_settings_strong_buy_threshold():
    from bist_bot.ui.pages import overview_page

    source = inspect.getsource(overview_page)

    assert "settings.STRONG_BUY_THRESHOLD" in source
    assert "s.score >= 40" not in source


def test_overview_scan_metrics_prefer_session_scan_stats():
    from bist_bot.ui.pages.overview_page import _resolve_scan_metrics

    scanned_assets, actionable_signals = _resolve_scan_metrics(
        session_scan_stats={"generated": 4, "actionable": 2},
        latest_scan={"total_scanned": 108, "actionable": 0},
        summary={"total_analyzed": 25},
        signals=[object(), object()],
    )

    assert scanned_assets == 25
    assert actionable_signals == 2


def test_overview_scan_metrics_fall_back_to_latest_scan_when_session_empty():
    from bist_bot.ui.pages.overview_page import _resolve_scan_metrics

    scanned_assets, actionable_signals = _resolve_scan_metrics(
        session_scan_stats={"generated": 0, "actionable": 0},
        latest_scan={"total_scanned": 108, "actionable": 3},
        summary={"total_analyzed": 0},
        signals=[],
    )

    assert scanned_assets == 108
    assert actionable_signals == 3


def test_overview_rejection_breakdown_renders_top_three_sorted_rows():
    from bist_bot.ui.pages.overview_page import _render_rejection_breakdown

    html_output = _render_rejection_breakdown(
        {
            "total_rejections": 9,
            "by_reason": [
                {"reason_code": "score_filtered_sideways", "count": 4},
                {"reason_code": "insufficient_history", "count": 3},
                {"reason_code": "mtf_confluence_blocked", "count": 2},
                {"reason_code": "adx_missing", "count": 1},
            ],
            "by_stage": [
                {"stage": "scoring", "count": 5},
                {"stage": "mtf", "count": 3},
                {"stage": "risk", "count": 1},
            ],
            "scan_id": "scan-overview",
        }
    )

    assert "En yaygın blokajlar" in html_output
    assert "Aşama dağılımı" in html_output
    assert "score_filtered_sideways" in html_output
    assert "insufficient_history" in html_output
    assert "mtf_confluence_blocked" in html_output
    assert "adx_missing" not in html_output
    assert "Skorlama 5" in html_output
    assert "MTF 3" in html_output
    assert "Risk 1" in html_output


def test_overview_stage_summary_renders_top_three_and_falls_back_for_unknown_stage():
    from bist_bot.ui.pages.overview_page import _render_rejection_stage_summary

    html_output = _render_rejection_stage_summary(
        {
            "total_rejections": 7,
            "by_reason": [],
            "by_stage": [
                {"stage": "scoring", "count": 3},
                {"stage": "custom_gate", "count": 2},
                {"stage": "risk", "count": 1},
                {"stage": "mtf", "count": 1},
            ],
            "scan_id": "scan-stage",
        }
    )

    assert "Aşama dağılımı" in html_output
    assert "Skorlama 3" in html_output
    assert "custom_gate 2" in html_output
    assert "Risk 1" in html_output
    assert "MTF 1" not in html_output


def test_overview_stage_summary_skips_empty_rejection_state():
    from bist_bot.ui.pages.overview_page import _render_rejection_stage_summary

    assert (
        _render_rejection_stage_summary(
            {
                "total_rejections": 0,
                "by_reason": [],
                "by_stage": [{"stage": "scoring", "count": 4}],
                "scan_id": "scan-empty",
            }
        )
        == ""
    )


def test_scan_detail_breakdown_list_renders_top_five_rows_with_fallback_label():
    from bist_bot.ui.pages.scan_detail_page import _render_breakdown_list

    html_output = _render_breakdown_list(
        title="Top rejection stages",
        subtitle="Pipeline dagilimi",
        rows=[
            {"stage": "scoring", "count": 5},
            {"stage": "risk", "count": 4},
            {"stage": "mtf", "count": 3},
            {"stage": "custom_gate", "count": 2},
            {"stage": "data", "count": 1},
            {"stage": "indicators", "count": 1},
        ],
        key_name="stage",
        label_fn=lambda stage: {
            "scoring": "Skorlama",
            "risk": "Risk",
            "mtf": "MTF",
            "data": "Veri",
        }.get(stage, stage),
        empty_message="Bos",
    )

    assert "Top rejection stages" in html_output
    assert "Skorlama" in html_output
    assert "custom_gate" in html_output
    assert "Veri" in html_output
    assert "indicators" not in html_output


def test_scan_detail_breakdown_list_returns_empty_message_without_rows():
    from bist_bot.ui.pages.scan_detail_page import _render_breakdown_list

    html_output = _render_breakdown_list(
        title="Top rejection reasons",
        subtitle="Adaylar",
        rows=[],
        key_name="reason_code",
        label_fn=lambda reason: reason,
        empty_message="Veri yok",
    )

    assert "Veri yok" in html_output


def test_scan_detail_summary_chips_use_top_reason_and_stage_from_sorted_payload():
    from bist_bot.ui.pages.scan_detail_page import _render_scan_summary_chips

    html_output = _render_scan_summary_chips(
        rejection_breakdown={
            "total_rejections": 7,
            "by_reason": [
                {"reason_code": "score_filtered_sideways", "count": 4},
                {"reason_code": "insufficient_history", "count": 3},
            ],
            "by_stage": [
                {"stage": "scoring", "count": 5},
                {"stage": "mtf", "count": 2},
            ],
            "scan_id": "scan-chip",
        },
        total_scanned=20,
    )

    assert "Top blocker" in html_output
    assert "Yatay piyasa filtresi" in html_output
    assert "score_filtered_sideways" in html_output
    assert "Top stage" in html_output
    assert "Skorlama" in html_output
    assert "scoring" in html_output
    assert "Rejection rate" in html_output
    assert "%35.0" in html_output


def test_scan_detail_summary_chips_handle_zero_scans_and_unknown_keys_safely():
    from bist_bot.ui.pages.scan_detail_page import _render_scan_summary_chips

    html_output = _render_scan_summary_chips(
        rejection_breakdown={
            "total_rejections": 0,
            "by_reason": [{"reason_code": "custom_gate", "count": 2}],
            "by_stage": [{"stage": "custom_stage", "count": 1}],
            "scan_id": "scan-zero",
        },
        total_scanned=0,
    )

    assert "custom_gate" in html_output
    assert "custom_stage" in html_output
    assert "%0.0" in html_output


def test_scan_detail_rejection_rate_formats_safely():
    from bist_bot.ui.pages.scan_detail_page import _format_rejection_rate

    assert _format_rejection_rate(5, 20) == "%25.0"
    assert _format_rejection_rate(0, 0) == "%0.0"


def test_scan_detail_rejection_rate_history_renders_recent_rows():
    from bist_bot.ui.pages.scan_detail_page import _render_rejection_rate_history

    html_output = _render_rejection_rate_history(
        [
            {
                "scan_id": "scan-002",
                "timestamp": "2026-05-01T10:00:00+03:00",
                "rejection_rate": 40.0,
                "total_rejections": 8,
                "total_scanned": 20,
                "top_reason": {"reason_code": "score_filtered_sideways", "count": 5},
            },
            {
                "scan_id": "scan-001",
                "timestamp": "2026-04-30T10:00:00+03:00",
                "rejection_rate": 10.0,
                "total_rejections": 2,
                "total_scanned": 20,
                "top_reason": {"reason_code": "insufficient_history", "count": 2},
            },
        ]
    )

    assert "Recent rejection rates" in html_output
    assert "scan-002" in html_output
    assert "%40.0" in html_output
    assert "score_filtered_sideways" in html_output


def test_scan_detail_history_summary_chips_use_aggregated_history_payload():
    from bist_bot.ui.pages.scan_detail_page import _render_history_summary_chips

    html_output = _render_history_summary_chips(
        {
            "window_size": 20,
            "returned_scans": 7,
            "average_rejection_rate": 22.5,
            "by_reason": [{"reason_code": "score_filtered_sideways", "count": 9}],
            "by_stage": [{"stage": "scoring", "count": 11}],
        }
    )

    assert "Last N scans" in html_output
    assert "7/20" in html_output
    assert "Most frequent blocker" in html_output
    assert "Yatay piyasa filtresi" in html_output
    assert "%22.5" in html_output


def test_scan_detail_page_shows_empty_state_when_no_completed_scan():
    from bist_bot.ui.pages import scan_detail_page

    class DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    response = SimpleNamespace(
        ok=True,
        json=lambda: {
            "stats": {
                "latest_scan": {
                    "total_scanned": 0,
                    "signals_generated": 0,
                    "actionable": 0,
                    "timestamp": None,
                },
                "rejection_breakdown": {
                    "total_rejections": 0,
                    "by_reason": [],
                    "by_stage": [],
                    "scan_id": "",
                },
            }
        },
    )

    with (
        patch.object(scan_detail_page, "api_request", return_value=response),
        patch.object(scan_detail_page, "render_page_hero"),
        patch.object(scan_detail_page, "render_metric_block"),
        patch.object(scan_detail_page, "render_section_title") as mock_section_title,
        patch.object(scan_detail_page, "render_html_panel") as mock_render_html_panel,
        patch.object(
            scan_detail_page.st, "columns", return_value=tuple(DummyColumn() for _ in range(4))
        ),
    ):
        scan_detail_page.render_scan_detail_page()

    mock_section_title.assert_called_with("Scan durumu", "Bekleyen veri")
    empty_panels = [call.args[0] for call in mock_render_html_panel.call_args_list]
    assert any("Henuz tamamlanmis bir scan kaydi bulunmuyor" in panel for panel in empty_panels)


def test_scan_detail_page_renders_historical_analytics_when_history_exists():
    from bist_bot.ui.pages import scan_detail_page

    class DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    stats_response = SimpleNamespace(
        ok=True,
        json=lambda: {
            "stats": {
                "latest_scan": {
                    "total_scanned": 20,
                    "signals_generated": 6,
                    "actionable": 4,
                    "timestamp": "2026-05-01T10:00:00+03:00",
                },
                "rejection_breakdown": {
                    "total_rejections": 8,
                    "by_reason": [{"reason_code": "score_filtered_sideways", "count": 5}],
                    "by_stage": [{"stage": "scoring", "count": 5}],
                    "scan_id": "scan-live",
                },
            }
        },
    )
    history_response = SimpleNamespace(
        ok=True,
        json=lambda: {
            "history": {
                "window_size": 20,
                "returned_scans": 2,
                "average_rejection_rate": 25.0,
                "by_reason": [{"reason_code": "score_filtered_sideways", "count": 7}],
                "by_stage": [{"stage": "scoring", "count": 7}],
                "scans": [
                    {
                        "scan_id": "scan-live",
                        "timestamp": "2026-05-01T10:00:00+03:00",
                        "rejection_rate": 40.0,
                        "total_rejections": 8,
                        "total_scanned": 20,
                        "top_reason": {"reason_code": "score_filtered_sideways", "count": 5},
                    },
                    {
                        "scan_id": "scan-prev",
                        "timestamp": "2026-04-30T10:00:00+03:00",
                        "rejection_rate": 10.0,
                        "total_rejections": 2,
                        "total_scanned": 20,
                        "top_reason": {"reason_code": "insufficient_history", "count": 2},
                    },
                ],
            }
        },
    )

    with (
        patch.object(
            scan_detail_page, "api_request", side_effect=[stats_response, history_response]
        ),
        patch.object(scan_detail_page, "render_page_hero"),
        patch.object(scan_detail_page, "render_metric_block"),
        patch.object(scan_detail_page, "render_section_title") as mock_section_title,
        patch.object(scan_detail_page, "render_html_panel") as mock_render_html_panel,
        patch.object(
            scan_detail_page.st,
            "columns",
            side_effect=[
                tuple(DummyColumn() for _ in range(4)),
                tuple(DummyColumn() for _ in range(2)),
                tuple(DummyColumn() for _ in range(2)),
            ],
        ),
    ):
        scan_detail_page.render_scan_detail_page()

    section_calls = [call.args for call in mock_section_title.call_args_list]
    assert ("Historical Analytics", "Son 20 scan trendi") in section_calls
    history_panels = [call.args[0] for call in mock_render_html_panel.call_args_list]
    assert any("Most frequent blockers" in panel for panel in history_panels)
    assert any("Recent rejection rates" in panel for panel in history_panels)


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
