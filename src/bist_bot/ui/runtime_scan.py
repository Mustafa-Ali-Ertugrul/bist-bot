"""Scan orchestration helpers for the Streamlit runtime."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.streamlit_utils import check_signals, send_signal_notification
from bist_bot.ui.runtime_types import ScanResult

TR = timezone(timedelta(hours=3))
SCAN_LOCK = threading.Lock()
PENDING_SCAN_RESULTS: dict[str, ScanResult] = {}
ACTIVE_SCAN_SESSIONS: set[str] = set()


def _should_clear_cache(scan_started_at: datetime, last_scan_time: datetime | None, force_clear: bool) -> bool:
    """Decide whether cached market data should be invalidated before scanning."""
    if force_clear:
        return True
    if last_scan_time is None:
        return False
    age = (scan_started_at - last_scan_time).total_seconds()
    return age > 900


def _session_dependencies() -> tuple[Any, Any, Any, Any, datetime | None]:
    """Read the current session-scoped runtime dependencies."""
    return (
        st.session_state.data_fetcher,
        st.session_state.engine,
        st.session_state.notifier,
        st.session_state.db,
        st.session_state.get("last_scan_time"),
    )


def _empty_scan_result(last_scan_time: datetime | None, error: str) -> ScanResult:
    """Build a consistent error payload for failed background scans."""
    return {
        "all_data": {},
        "signals": [],
        "last_scan_time": last_scan_time,
        "error": error,
    }


def collect_scan_result(fetcher, engine, notifier, db, last_scan_time: datetime | None = None, force_clear: bool = False) -> ScanResult:
    """Run one scan cycle and return the runtime payload."""
    scan_started_at = datetime.now(TR)
    if _should_clear_cache(scan_started_at, last_scan_time, force_clear):
        fetcher.clear_cache(scope="intraday_fetch")
        fetcher.clear_cache(scope="analysis")

    timeframe_data = fetcher.fetch_multi_timeframe_all(
        trend_period=settings.MTF_TREND_PERIOD,
        trend_interval=settings.MTF_TREND_INTERVAL,
        trigger_period=settings.MTF_TRIGGER_PERIOD,
        trigger_interval=settings.MTF_TRIGGER_INTERVAL,
        force_refresh=force_clear,
    )
    signals = engine.scan_all(timeframe_data)
    all_data = {ticker: data["trigger"] for ticker, data in timeframe_data.items() if isinstance(data, dict) and "trigger" in data}

    db.save_signals(signals)

    for ticker, market_data in timeframe_data.items():
        signal = check_signals(ticker, market_data, engine=engine)
        if signal is not None:
            send_signal_notification(signal, notifier)

    return {"all_data": all_data, "signals": signals, "last_scan_time": scan_started_at, "error": None}


def apply_scan_result(scan_result: ScanResult) -> None:
    """Write a completed scan result into Streamlit session state."""
    st.session_state.all_data = scan_result["all_data"]
    st.session_state.signals = scan_result["signals"]
    st.session_state.last_scan_time = scan_result["last_scan_time"]
    st.session_state.scan_error = scan_result.get("error")
    st.session_state.scan_in_progress = False


def run_scan(force_clear: bool = False) -> None:
    """Execute a synchronous scan using the session-scoped dependencies."""
    fetcher, engine, notifier, db, last_scan_time = _session_dependencies()
    result = collect_scan_result(
        fetcher=fetcher,
        engine=engine,
        notifier=notifier,
        db=db,
        last_scan_time=last_scan_time,
        force_clear=force_clear,
    )
    apply_scan_result(result)


def start_background_scan(force_clear: bool = False) -> bool:
    """Start a background scan for the current Streamlit session."""
    session_key = st.session_state.get("_scan_session_key")
    if not session_key:
        return False
    with SCAN_LOCK:
        if session_key in ACTIVE_SCAN_SESSIONS:
            return False
        ACTIVE_SCAN_SESSIONS.add(session_key)

    fetcher, engine, notifier, db, last_scan_time = _session_dependencies()
    st.session_state.scan_in_progress = True
    st.session_state.scan_error = None

    def worker():
        try:
            result = collect_scan_result(fetcher, engine, notifier, db, last_scan_time=last_scan_time, force_clear=force_clear)
        except Exception as exc:
            result = _empty_scan_result(last_scan_time, str(exc))
        with SCAN_LOCK:
            PENDING_SCAN_RESULTS[session_key] = result
            ACTIVE_SCAN_SESSIONS.discard(session_key)

    threading.Thread(target=worker, daemon=True).start()
    return True


def apply_pending_scan_result() -> bool:
    """Apply a finished background scan when available."""
    session_key = st.session_state.get("_scan_session_key")
    if not session_key:
        return False
    with SCAN_LOCK:
        pending_result = PENDING_SCAN_RESULTS.pop(session_key, None)
        is_active = session_key in ACTIVE_SCAN_SESSIONS
    st.session_state.scan_in_progress = is_active
    if pending_result is None:
        return False
    if pending_result.get("error"):
        st.session_state.scan_error = pending_result["error"]
        st.session_state.scan_in_progress = False
        return True
    apply_scan_result(pending_result)
    return True


def ensure_initial_data() -> None:
    """Load cached signals or trigger the first scan for the UI session."""
    apply_pending_scan_result()
    if st.session_state.signals:
        return
    try:
        from bist_bot.ui.runtime_data import map_cached_signals

        cached = st.session_state.db.get_recent_signals(limit=len(settings.WATCHLIST))
        if cached:
            st.session_state.signals = map_cached_signals(cached)
            start_background_scan(force_clear=False)
            return
        run_scan(force_clear=False)
        st.rerun()
    except Exception as exc:
        st.error(f"Tarama hatasi: {exc}")
