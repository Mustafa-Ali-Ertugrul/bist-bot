"""Scan orchestration helpers for the Streamlit runtime."""

from __future__ import annotations

import threading
from collections.abc import MutableMapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import streamlit as st

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import SignalType
from bist_bot.streamlit_utils import check_signals, send_signal_notification
from bist_bot.ui.runtime_types import ScanResult, ScanStats
from bist_bot.ui.session_cooldown import consume_cooldown

TR = timezone(timedelta(hours=3))
EMPTY_REJECTION_BREAKDOWN = {
    "total_rejections": 0,
    "by_reason": [],
    "by_stage": [],
    "scan_id": "",
}
SCAN_LOCK = threading.Lock()
PENDING_SCAN_RESULTS: dict[str, ScanResult] = {}
ACTIVE_SCAN_SESSIONS: set[str] = set()

logger = get_logger(__name__, component="ui_scan")


def _should_clear_cache(
    scan_started_at: datetime, last_scan_time: datetime | None, force_clear: bool
) -> bool:
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
    empty_stats: ScanStats = {"generated": 0, "actionable": 0, "hold": 0}
    return {
        "all_data": {},
        "signals": [],
        "last_scan_time": last_scan_time,
        "error": error,
        "scan_stats": empty_stats,
        "rejection_breakdown": dict(EMPTY_REJECTION_BREAKDOWN),
    }


def _set_scan_phase(phase: str) -> None:
    """Publish scan progress for the Streamlit UI and logs."""
    st.session_state.scan_phase = phase
    logger.info("ui_scan_phase", phase=phase)


def collect_scan_result(
    fetcher,
    engine,
    notifier,
    db,
    last_scan_time: datetime | None = None,
    force_clear: bool = False,
    limited_tickers: list[str] | None = None,
) -> ScanResult:
    """Run one scan cycle and return the runtime payload."""
    scan_started_at = datetime.now(TR)
    if _should_clear_cache(scan_started_at, last_scan_time, force_clear):
        _set_scan_phase("Cache temizleniyor")
        fetcher.clear_cache(scope="intraday_fetch")
        fetcher.clear_cache(scope="analysis")

    if limited_tickers:
        _set_scan_phase(f"{len(limited_tickers)} hisse icin veri aliniyor")
        timeframe_data = fetcher.fetch_multi_timeframe(
            tickers=limited_tickers,
            trend_period=settings.MTF_TREND_PERIOD,
            trend_interval=settings.MTF_TREND_INTERVAL,
            trigger_period=settings.MTF_TRIGGER_PERIOD,
            trigger_interval=settings.MTF_TRIGGER_INTERVAL,
            force_refresh=force_clear,
        )
    else:
        _set_scan_phase("Tum izleme listesi icin veri aliniyor")
        timeframe_data = fetcher.fetch_multi_timeframe_all(
            trend_period=settings.MTF_TREND_PERIOD,
            trend_interval=settings.MTF_TREND_INTERVAL,
            trigger_period=settings.MTF_TRIGGER_PERIOD,
            trigger_interval=settings.MTF_TRIGGER_INTERVAL,
            force_refresh=force_clear,
        )
    _set_scan_phase(f"{len(timeframe_data)} hisse analiz ediliyor")
    signals = engine.scan_all(timeframe_data)
    breakdown_getter = getattr(engine, "get_last_rejection_breakdown", None)
    rejection_breakdown = (
        breakdown_getter() if callable(breakdown_getter) else dict(EMPTY_REJECTION_BREAKDOWN)
    )
    all_data = {
        ticker: data["trigger"]
        for ticker, data in timeframe_data.items()
        if isinstance(data, dict) and "trigger" in data
    }

    _set_scan_phase("Sonuclar kaydediliyor")
    try:
        db.save_signals(signals)
    except Exception as exc:
        logger.warning("ui_scan_signal_save_failed", error_type=type(exc).__name__, error=str(exc))
    save_breakdown = getattr(db, "save_latest_rejection_breakdown", None)
    if callable(save_breakdown):
        try:
            save_breakdown(
                rejection_breakdown
                if isinstance(rejection_breakdown, dict)
                else EMPTY_REJECTION_BREAKDOWN
            )
        except Exception as exc:
            logger.warning(
                "ui_scan_breakdown_save_failed", error_type=type(exc).__name__, error=str(exc)
            )

    buy_count = sum(
        1
        for signal in signals
        if signal.signal_type in {SignalType.BUY, SignalType.STRONG_BUY, SignalType.WEAK_BUY}
    )
    sell_count = sum(
        1
        for signal in signals
        if signal.signal_type in {SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL}
    )

    for ticker, market_data in timeframe_data.items():
        signal = check_signals(ticker, market_data, engine=engine)
        if signal is not None:
            send_signal_notification(signal, notifier)

    hold_count = sum(1 for signal in signals if signal.signal_type == SignalType.HOLD)
    actionable_count = len(signals) - hold_count
    normalized_breakdown = (
        rejection_breakdown
        if isinstance(rejection_breakdown, dict)
        else dict(EMPTY_REJECTION_BREAKDOWN)
    )
    try:
        db.save_scan_log(
            len(timeframe_data),
            len(signals),
            buy_count,
            sell_count,
            actionable_count,
            scan_id=str(normalized_breakdown.get("scan_id", "") or ""),
            rejection_breakdown=normalized_breakdown,
        )
    except Exception as exc:
        logger.warning("ui_scan_log_save_failed", error_type=type(exc).__name__, error=str(exc))
    scan_stats: ScanStats = {
        "generated": len(signals),
        "actionable": actionable_count,
        "hold": hold_count,
    }

    result: ScanResult = {
        "all_data": all_data,
        "signals": signals,
        "last_scan_time": scan_started_at,
        "error": None,
        "scan_stats": scan_stats,
        "rejection_breakdown": normalized_breakdown,
    }
    _set_scan_phase("Tarama tamamlandi")
    return result


def apply_scan_result(scan_result: ScanResult) -> None:
    """Write a completed scan result into Streamlit session state."""
    st.session_state.all_data = scan_result["all_data"]
    st.session_state.signals = scan_result["signals"]
    st.session_state.last_scan_time = scan_result["last_scan_time"]
    st.session_state.scan_error = scan_result.get("error")
    st.session_state.scan_phase = None
    st.session_state.scan_stats = scan_result.get(
        "scan_stats", {"generated": 0, "actionable": 0, "hold": 0}
    )
    st.session_state.rejection_breakdown = scan_result.get(
        "rejection_breakdown", dict(EMPTY_REJECTION_BREAKDOWN)
    )
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


def run_initial_scan(force_clear: bool = False, limited: bool = True) -> bool:
    """Run the first scan synchronously so the dashboard does not render empty."""
    if st.session_state.get("all_data"):
        return True

    fetcher, engine, notifier, db, last_scan_time = _session_dependencies()
    limited_tickers = None
    if limited:
        limit = int(getattr(settings, "STREAMLIT_INITIAL_SCAN_LIMIT", 10))
        watchlist = list(getattr(settings, "WATCHLIST", []))
        limited_tickers = watchlist[:limit] if watchlist else None

    st.session_state.scan_in_progress = True
    st.session_state.scan_started_at = datetime.now(TR)
    st.session_state.scan_error = None
    st.session_state.scan_phase = "Ilk tarama baslatiliyor"
    try:
        result = collect_scan_result(
            fetcher=fetcher,
            engine=engine,
            notifier=notifier,
            db=db,
            last_scan_time=last_scan_time,
            force_clear=force_clear,
            limited_tickers=limited_tickers,
        )
        apply_scan_result(result)
        return bool(st.session_state.get("all_data"))
    except Exception as exc:
        st.session_state.scan_in_progress = False
        st.session_state.scan_error = str(exc)
        logger.error("ui_initial_sync_scan_failed", error=str(exc))
        return False


def request_scan(force_clear: bool = False) -> bool:
    allowed, remaining = consume_cooldown(
        cast(MutableMapping[str, Any], st.session_state),
        action="scan",
        cooldown_seconds=float(getattr(settings, "STREAMLIT_SCAN_COOLDOWN_SECONDS", 8.0)),
    )
    if not allowed:
        st.warning(f"Cok sik istek gonderildi, birkac saniye bekleyin. ({remaining:.1f}s)")
        return False
    run_scan(force_clear=force_clear)
    return True


def check_scan_timeout() -> bool:
    """Reset stale scan_in_progress if background scan exceeds timeout.

    Returns True if a timeout was detected and handled.
    """
    if not st.session_state.get("scan_in_progress"):
        return False
    scan_started_at = st.session_state.get("scan_started_at")
    if scan_started_at is None:
        return False
    timeout_seconds = int(getattr(settings, "STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS", 90))
    elapsed = (datetime.now(TR) - scan_started_at).total_seconds()
    if elapsed < timeout_seconds:
        return False
    session_key = st.session_state.get("_scan_session_key")
    logger.warning(
        "ui_background_scan_timeout",
        session_key=session_key,
        duration_seconds=round(elapsed, 1),
        timeout_seconds=timeout_seconds,
    )
    st.session_state.scan_in_progress = False
    st.session_state.scan_error = (
        f"Arka plan taramasi {timeout_seconds} saniye icinde tamamlanamadi. "
        "Manuel tarama baslatmayi deneyin."
    )
    st.session_state.scan_phase = None
    with SCAN_LOCK:
        ACTIVE_SCAN_SESSIONS.discard(session_key or "")
        PENDING_SCAN_RESULTS.pop(session_key or "", None)
    return True


def start_background_scan(force_clear: bool = False, limited: bool = False) -> bool:
    """Start a background scan for the current Streamlit session."""
    session_key = st.session_state.get("_scan_session_key")
    if not session_key:
        return False
    with SCAN_LOCK:
        if session_key in ACTIVE_SCAN_SESSIONS:
            return False
        ACTIVE_SCAN_SESSIONS.add(session_key)

    fetcher, engine, notifier, db, last_scan_time = _session_dependencies()
    scan_started_at = datetime.now(TR)
    st.session_state.scan_in_progress = True
    st.session_state.scan_started_at = scan_started_at
    st.session_state.scan_error = None
    st.session_state.scan_phase = "Tarama baslatiliyor"

    limited_tickers = None
    if limited:
        limit = int(getattr(settings, "STREAMLIT_INITIAL_SCAN_LIMIT", 20))
        watchlist = list(getattr(settings, "WATCHLIST", []))
        limited_tickers = watchlist[:limit] if watchlist else None

    logger.info(
        "ui_background_scan_started",
        session_key=session_key,
        limited=limited,
        ticker_count=len(limited_tickers) if limited_tickers else "all",
    )

    def worker():
        result = _empty_scan_result(last_scan_time, "scan did not complete")
        timeout_seconds = int(getattr(settings, "STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS", 45))
        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                collect_scan_result,
                fetcher=fetcher,
                engine=engine,
                notifier=notifier,
                db=db,
                last_scan_time=last_scan_time,
                force_clear=force_clear,
                limited_tickers=limited_tickers,
            )
            try:
                result = future.result(timeout=timeout_seconds)
            except TimeoutError:
                future.cancel()
                result = _empty_scan_result(
                    last_scan_time,
                    f"Tarama {timeout_seconds} saniye icinde tamamlanamadi.",
                )
                logger.warning(
                    "ui_background_scan_worker_timeout",
                    session_key=session_key,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            logger.info(
                "ui_background_scan_completed",
                session_key=session_key,
                duration_seconds=round((datetime.now(TR) - scan_started_at).total_seconds(), 1),
                signal_count=len(result.get("signals", [])),
            )
        except Exception as exc:
            result = _empty_scan_result(last_scan_time, str(exc))
            logger.error(
                "ui_background_scan_failed",
                session_key=session_key,
                error=str(exc),
            )
        finally:
            result["scan_phase"] = st.session_state.get("scan_phase")
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
        st.session_state.scan_phase = pending_result.get("scan_phase")
        st.session_state.scan_in_progress = False
        return True
    apply_scan_result(pending_result)
    return True


def ensure_initial_data() -> None:
    """Load cached signals without starting first-render scans in the background."""
    apply_pending_scan_result()
    if st.session_state.get("all_data") or st.session_state.signals:
        return
    if st.session_state.get("scan_in_progress"):
        return
    try:
        from bist_bot.ui.runtime_data import map_cached_signals

        cached = st.session_state.db.get_recent_signals(limit=len(settings.WATCHLIST))
        if cached:
            st.session_state.signals = map_cached_signals(cached)
            start_background_scan(force_clear=False, limited=False)
            return
        if start_background_scan(force_clear=False, limited=True):
            st.session_state.scan_in_progress = True
    except Exception as exc:
        logger.error("ui_initial_scan_failed", error=str(exc))
        st.error(f"Tarama hatasi: {exc}")
