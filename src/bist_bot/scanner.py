"""Scan orchestration service shared by CLI and dashboard flows."""

import time
from datetime import UTC, date, datetime
from typing import cast

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter, set_gauge
from bist_bot.config.settings import Settings
from bist_bot.config.settings import settings as default_settings
from bist_bot.contracts import (
    DataFetcherProtocol,
    ExecutionProviderProtocol,
    NotifierProtocol,
    SignalRepositoryProtocol,
    StrategyEngineProtocol,
)
from bist_bot.market_calendar import TR, is_bist_open
from bist_bot.observability.logging import log_signal
from bist_bot.observability.metrics import record_signal
from bist_bot.risk.circuit_breaker import CircuitBreaker
from bist_bot.services.execution_service import ExecutionService
from bist_bot.services.notification_service import NotificationDispatchService
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.services.shadow_trade_service import ShadowTradeService
from bist_bot.services.signal_change_service import SignalChangeService
from bist_bot.services.signal_outcome_tracker import SignalOutcomeTracker
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import (
    Signal,
    SignalCategory,
    SignalType,
    categorize_signal,
)

logger = get_logger(__name__, component="scanner")
EMPTY_REJECTION_BREAKDOWN = {
    "total_rejections": 0,
    "by_reason": [],
    "by_stage": [],
    "scan_id": "",
}


class ScanService:
    """Coordinate one market scan from data fetch through side effects.

    The service is the orchestration boundary shared by the CLI worker,
    Flask API, and tests. It deliberately delegates domain work to injected
    collaborators: the fetcher loads market data, the strategy engine scores
    it, repositories persist results, and side-effect services handle
    notifications, execution, and paper-trade lifecycle updates.

    `scan_once` is intentionally synchronous so callers can reason about one
    complete scan transaction at a time. Failures are logged with metrics and
    then re-raised, allowing schedulers or API handlers to decide retry/HTTP
    behavior.
    """

    def __init__(
        self,
        fetcher: DataFetcherProtocol,
        engine: StrategyEngineProtocol,
        notifier: NotifierProtocol,
        db: SignalRepositoryProtocol,
        broker: ExecutionProviderProtocol | None = None,
        settings: Settings | None = None,
        signal_change_service: SignalChangeService | None = None,
        execution_service: ExecutionService | None = None,
        paper_trade_service: PaperTradeService | None = None,
        notification_service: NotificationDispatchService | None = None,
        shadow_trade_service: ShadowTradeService | None = None,
        signal_outcome_tracker: SignalOutcomeTracker | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        """Create a scan service with explicit runtime dependencies."""
        self.fetcher = fetcher
        self.engine = engine
        self.notifier = notifier
        self.db = db
        self.broker = broker
        self.settings = settings or default_settings
        self.signal_change_service = signal_change_service or SignalChangeService(
            db,
            notifier,
            params=StrategyParams.from_settings(),
            min_score_delta=getattr(self.settings, "SIGNAL_CHANGE_MIN_SCORE_DELTA", None),
        )
        self.execution_service = execution_service or ExecutionService(
            db, broker=broker, settings=self.settings
        )
        self.paper_trade_service = paper_trade_service or PaperTradeService(
            fetcher, db, settings=self.settings, alerter=notifier.send_message
        )
        self.notification_service = notification_service or NotificationDispatchService(
            notifier, settings=self.settings
        )
        self.shadow_trade_service = shadow_trade_service or ShadowTradeService(
            settings=self.settings
        )
        self.signal_outcome_tracker = signal_outcome_tracker or SignalOutcomeTracker(
            settings=self.settings, db=self.db
        )
        self.last_scan_stats: dict[str, int] = {
            "scanned": 0,
            "actionable": 0,
            "buys": 0,
            "sells": 0,
        }
        self.last_side_effects: dict[str, bool] = {"paper_trades_queued": False}
        self.last_rejection_breakdown: dict[str, object] = dict(EMPTY_REJECTION_BREAKDOWN)
        self.circuit_breaker = circuit_breaker
        # B4: gunluk bir kez stale-warning spam onlemi.
        self._last_stale_warn_date: date | None = None

    def _auto_execute_signals(self, signals: list[Signal]) -> None:
        """Submit actionable signals to the configured execution service."""
        self.execution_service.auto_execute_signals(signals)

    def _check_signal_changes(self, signals: list[Signal]) -> None:
        """Detect signal changes and dispatch change notifications."""
        self.signal_change_service.check_signal_changes(signals)

    def _process_shadow_trades(self, signals: list[Signal], market_data: dict) -> None:
        """Run the observation ledger without affecting the live scan path."""
        try:
            closed = self.shadow_trade_service.process_scan(signals, market_data)
            self.shadow_trade_service.maybe_send_daily_summary(
                self.notifier,
                closed_this_scan=closed,
            )
        except Exception as exc:
            logger.exception("shadow_trade_processing_failed", error=exc)

    def _process_signal_outcomes(self, signals: list[Signal], market_data: dict) -> None:
        """Run outcome tracking for AL signals (shadow pattern, isolated)."""
        try:
            self.signal_outcome_tracker.process_scan(signals, market_data)
        except Exception as exc:
            logger.exception("signal_outcome_processing_failed", error=exc)

    def scan_once(self, force_refresh: bool = False) -> list[Signal]:
        """Run one complete scan and return all generated signals.

        When `force_refresh` is true, intraday fetch and analysis caches are
        invalidated before data loading. Only actionable signals are persisted
        and queued for execution/paper trading, but the full signal list is
        returned to callers for UI and diagnostics.
        """
        started_at = time.perf_counter()
        watchlist = list(getattr(self.settings, "WATCHLIST", []) or [])
        logger.info(
            "scan_started",
            scanned_count=len(watchlist),
            watchlist_source=str(getattr(self.settings, "WATCHLIST_SOURCE", "")),
            component="scanner",
        )

        if not watchlist:
            logger.warning(
                "scan_aborted_empty_watchlist",
                watchlist_source=str(getattr(self.settings, "WATCHLIST_SOURCE", "")),
            )
            self.last_scan_stats = {
                "scanned": 0,
                "signals": 0,
                "actionable": 0,
                "buys": 0,
                "sells": 0,
            }
            return []

        # Keep fetcher universe aligned with active settings watchlist.
        try:
            self.fetcher.watchlist = watchlist
        except Exception as exc:
            logger.warning(
                "scanner_fetcher_watchlist_sync_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

        if self.circuit_breaker and not self.circuit_breaker.allow_request():
            logger.warning("scan_aborted_circuit_open")
            return []

        try:
            self.last_side_effects["paper_trades_queued"] = False
            if force_refresh:
                self.fetcher.clear_cache(scope="intraday_fetch")
                self.fetcher.clear_cache(scope="analysis")
            all_data = self.fetcher.fetch_multi_timeframe_all(
                trend_period=getattr(self.settings, "MTF_TREND_PERIOD", "6mo"),
                trend_interval=getattr(self.settings, "MTF_TREND_INTERVAL", "1d"),
                trigger_period=getattr(self.settings, "MTF_TRIGGER_PERIOD", "1mo"),
                trigger_interval=getattr(self.settings, "MTF_TRIGGER_INTERVAL", "15m"),
                force_refresh=force_refresh,
            )
            skipped_getter = getattr(self.fetcher, "get_last_skipped_tickers", None)
            skipped_tickers = list(skipped_getter() or []) if callable(skipped_getter) else []
            if skipped_tickers:
                logger.warning(
                    "scan_tickers_skipped",
                    skipped_count=len(skipped_tickers),
                    skipped_tickers=",".join(skipped_tickers[:20]),
                )

            # B4: bayat veriyle sinyal uretilmesin — taze olmayan ticker'lar
            # atilir, oran kritikse tarama tamamen durdurulur.
            all_data = self._apply_freshness_gate(all_data)

            if not all_data:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                inc_counter("bist_scan_fail_total")
                set_gauge("bist_last_scan_duration_ms", duration_ms)
                set_gauge("bist_last_scan_scanned_count", 0)
                logger.error(
                    "scan_failed",
                    error_type="empty_fetch",
                    duration_ms=duration_ms,
                    scanned_count=0,
                )
                return []

            signals = self.engine.scan_all(all_data)
            breakdown_getter = getattr(self.engine, "get_last_rejection_breakdown", None)
            breakdown = (
                breakdown_getter()
                if callable(breakdown_getter)
                else dict(EMPTY_REJECTION_BREAKDOWN)
            )
            self.last_rejection_breakdown = (
                breakdown if isinstance(breakdown, dict) else dict(EMPTY_REJECTION_BREAKDOWN)
            )
            actionable = self.engine.get_actionable_signals(signals)
            self._process_shadow_trades(signals, all_data)
            actionable_buys = [s for s in actionable if s.signal_type.is_buy]
            actionable_sells = [s for s in actionable if s.signal_type.is_sell]
            al_signals = [s for s in signals if categorize_signal(s) is SignalCategory.AL]
            self.last_scan_stats = {
                "scanned": len(all_data),
                "signals": len(signals),
                # NOTE: 'actionable' counts only canonical AL signals (score >= buy_threshold).
                # Previously this counted all actionable types (buys + sells).  The new
                # semantic matches the daily report's "Actionable AL" column.  Historical
                # scan_log rows retain the old meaning — dashboard should label accordingly.
                "actionable": len(al_signals),
                "buys": len(actionable_buys),
                "sells": len(actionable_sells),
            }

            self._check_signal_changes(signals)
            self.db.save_signals(signals)
            self._process_signal_outcomes(signals, all_data)

            # BUG-5 fix: skip auto_execute when agent owns entries
            agent_enabled = bool(getattr(self.settings, "AGENT_ENABLED", False)) or bool(
                getattr(getattr(self.settings, "agent", None), "AGENT_ENABLED", False)
            )
            if agent_enabled:
                logger.info("agent_owns_entries_skip_auto_execute")
            else:
                self._auto_execute_signals(actionable)

            if getattr(self.settings, "PAPER_MODE", False):
                self.last_side_effects["paper_trades_queued"] = bool(
                    self.paper_trade_service.queue_actionable_signals(actionable)
                )
            self.db.save_scan_log(
                len(all_data),
                len(signals),
                len(actionable_buys),
                len(actionable_sells),
                len(al_signals),
                scan_id=str(self.last_rejection_breakdown.get("scan_id", "") or ""),
                rejection_breakdown=self.last_rejection_breakdown,
            )
            self.notification_service.notify_scan_results(signals, actionable, len(all_data))

            if getattr(self.settings, "PAPER_MODE", False):
                self.update_paper_trades(signals=signals)

            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            rejection_count = len(all_data) - len(signals)
            radar_count = sum(1 for s in signals if categorize_signal(s) is SignalCategory.RADAR)

            inc_counter("bist_scan_total")
            inc_counter("bist_signal_emitted_total", len(actionable))
            set_gauge("bist_last_scan_duration_ms", duration_ms)
            set_gauge("bist_last_scan_scanned_count", len(all_data))

            logger.info(
                "scan_summary",
                requested=len(watchlist),
                fetched=len(all_data),
                signals=len(signals),
                actionable=len(al_signals),
                radar=radar_count,
                rejected=rejection_count,
                buys=len(actionable_buys),
                sells=len(actionable_sells),
                duration_ms=duration_ms,
                scan_id=str(self.last_rejection_breakdown.get("scan_id", "") or ""),
            )

            for signal in signals:
                if signal.signal_type is not SignalType.HOLD:
                    record_signal(signal.signal_type.name)
                    log_signal(
                        signal.signal_type.name,
                        ticker=signal.ticker,
                        score=float(signal.score),
                        logger=logger,
                    )
                    logger.debug(
                        "signal_emitted",
                        ticker=signal.ticker,
                        signal_type=str(signal.signal_type),
                        score=signal.score,
                    )

            if self.circuit_breaker:
                self.circuit_breaker.record_success()

            return cast(list[Signal], signals)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            inc_counter("bist_scan_fail_total")
            set_gauge("bist_last_scan_duration_ms", duration_ms)
            logger.exception("scan_failed", error=exc, duration_ms=duration_ms)
            if hasattr(self, "circuit_breaker") and self.circuit_breaker:
                self.circuit_breaker.record_error()
            raise

    def update_paper_trades(self, signals: list["Signal"] | None = None) -> None:
        """Refresh open paper trades and close only triggered positions."""
        self.paper_trade_service.update_open_trades(signals=signals)

    # ------------------------------------------------------------------
    # B4 — candle freshness gate
    # ------------------------------------------------------------------
    @staticmethod
    def _last_bar_age_minutes(df: pd.DataFrame | None) -> float | None:
        """Age of the newest bar in minutes; None when undeterminable."""
        if df is None or getattr(df, "empty", True):
            return None
        ts = None
        try:
            if "date" in getattr(df, "columns", []):
                ts = pd.Timestamp(df["date"].iloc[-1])
            elif isinstance(df.index, pd.DatetimeIndex) or len(df.index) > 0:
                ts = pd.Timestamp(df.index[-1])
        except Exception:
            return None
        if ts is None or pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        now = pd.Timestamp.now(tz="UTC")
        return (now - ts.tz_convert("UTC")).total_seconds() / 60.0

    def _apply_freshness_gate(
        self, all_data: dict[str, dict[str, pd.DataFrame]]
    ) -> dict[str, dict[str, pd.DataFrame]]:
        """Drop tickers whose trigger bars are stale (B4).

        Only active during market hours — outside the session all bars are
        "old" by definition. Ratio bands (settings):
        - >= STALE_SYMBOL_WARN_RATIO: Telegram warning (once/day).
        - >= STALE_SYMBOL_HALT_RATIO: scan aborted entirely — publishing
          signals built on a mostly-stale dataset would fake confidence.
        """
        if not is_bist_open():
            return all_data
        max_age = max(1, int(getattr(self.settings, "STALE_BAR_MAX_AGE_MINUTES", 30)))
        warn_ratio = float(getattr(self.settings, "STALE_SYMBOL_WARN_RATIO", 0.20))
        halt_ratio = float(getattr(self.settings, "STALE_SYMBOL_HALT_RATIO", 0.40))

        total = len(all_data)
        if total == 0:
            return all_data

        stale: list[str] = []
        for ticker, frames in all_data.items():
            trigger_df = frames.get("trigger") if isinstance(frames, dict) else None
            age = self._last_bar_age_minutes(trigger_df)
            if age is not None and age > max_age:
                stale.append(ticker)

        ratio = len(stale) / total
        inc_counter("bist_stale_data_total", len(stale))
        set_gauge("bist_stale_symbol_ratio", round(ratio, 4))
        if stale:
            logger.warning(
                "scan_stale_tickers",
                stale_count=len(stale),
                total=total,
                ratio=round(ratio, 3),
                max_age_minutes=max_age,
                stale_sample=",".join(sorted(stale)[:10]),
            )

        if ratio >= halt_ratio:
            inc_counter("bist_scan_fail_total")
            logger.error(
                "scan_failed",
                error_type="stale_data_halt",
                stale_count=len(stale),
                total=total,
                ratio=round(ratio, 3),
            )
            try:
                self.notifier.send_message(
                    f"🛑 <b>Tarama durduruldu:</b> {len(stale)}/{total} hissenin verisi "
                    f"bayat (>{max_age} dk). Veri kaynağı bozuk — sinyal üretilmedi."
                )
            except Exception:
                logger.warning("stale_halt_alert_send_failed")
            return {}

        if ratio >= warn_ratio and self._last_stale_warn_date != datetime.now(TR).date():
            self._last_stale_warn_date = datetime.now(TR).date()
            try:
                self.notifier.send_message(
                    f"⚠️ <b>Veri tazeliği:</b> {len(stale)}/{total} hisse bayat "
                    f"(>{max_age} dk). Bu hisseler tarama dışı bırakıldı."
                )
            except Exception:
                logger.warning("stale_warn_alert_send_failed")

        for ticker in stale:
            all_data.pop(ticker, None)
        return all_data

    def close_positions_at_eod(self, *, now: datetime | None = None) -> None:
        """Faz 3 P1.1 — post-close discipline pass (silent, no signals/notifications).

        The scheduler calls this once per trading day shortly after
        ``bist_close_time``; without it the EOD contract in
        ``paper_trade_service._is_eod`` / ``SignalOutcomeTracker._is_eod``
        would never fire in production because no scan runs after market
        close.

        Behavior:
        - fetches fresh daily closes so ``EOD_CLOSE`` uses real exit prices;
        - paper positions close via ``update_open_trades(signals=None)``
          (fetch fallback supplies prices);
        - tracked AL outcomes close via ``process_scan([], market_data)``
          (empty signal list -> no new positions open);
        - sub-pass failures are logged AND surfaced (B2: the scheduler needs
          the failure to schedule a retry; EOD FAILED != EOD DONE).
        """
        effective_now = now or datetime.now(UTC)
        try:
            market_data = self.fetcher.fetch_all(period="1d", force=False) or {}
        except Exception as exc:
            logger.warning(
                "eod_close_fetch_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            market_data = {}

        # B2: best-effort degil — hata scheduler'a yukselir ki retry/devamsizlik
        # takibi (EOD FAILED != EOD DONE) calissin. Her iki alt-pass da denenir.
        failures: list[str] = []
        try:
            self.paper_trade_service.update_open_trades(signals=None, now=effective_now)
        except Exception as exc:
            failures.append("paper_close")
            logger.exception("eod_paper_close_failed", error=exc)

        try:
            self.signal_outcome_tracker.process_scan([], market_data, now=effective_now)
        except Exception as exc:
            failures.append("outcome_close")
            logger.exception("eod_outcome_close_failed", error=exc)

        if failures:
            raise RuntimeError(f"EOD pass kismi basarisiz: {', '.join(failures)}")

        logger.info("eod_close_pass_completed")
