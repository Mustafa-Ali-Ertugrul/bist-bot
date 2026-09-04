"""Scan orchestration service shared by CLI and dashboard flows."""

import threading
import time
from datetime import UTC, date, datetime, timedelta
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


def _interval_minutes(interval: str | None) -> float | None:
    """Candle length in minutes for yfinance-style intervals (15m, 1h, 1d, 1wk...)."""
    if not interval:
        return None
    s = interval.strip().lower()
    num = ""
    unit = ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            unit += ch
    try:
        n = float(num) if num else 1.0
    except ValueError:
        return None
    if unit == "m":
        return n
    if unit == "h":
        return n * 60
    if unit == "d":
        return n * 24 * 60
    if unit == "wk":
        return n * 7 * 24 * 60
    if unit == "mo":
        return n * 30 * 24 * 60
    return None


class ScanAbortedError(Exception):
    """Raised when a market scan is aborted via cooperative cancellation."""


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
            settings=self.settings, db=db
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
        # Stale-halt Telegram alert cooldown (default 120 dk — settings override).
        self._last_stale_halt_alert_at: datetime | None = None

    def _auto_execute_signals(self, signals: list[Signal]) -> None:
        """Submit actionable signals to the configured execution service."""
        if getattr(self.settings, "AUTO_EXECUTE_ENABLED", False) is not True:
            logger.info("auto_execute_disabled_by_independent_gate")
            return
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

    def _filter_duplicate_sats(self, signals: list[Signal]) -> list[Signal]:
        """Drop sell-family signals whose ticker already has a sell persisted for
        the current TR-local day. Also dedups within the same scan batch.

        Scope: persistence only — notifications, paper trades, and outcome
        tracking still see the full signal list (callers keep `signals`),
        which is what the user asked: max 1 persisted SAT per ticker per day.
        """
        if not any(s.signal_type.is_sell for s in signals):
            return signals
        today_tr = datetime.now(UTC).astimezone(TR).date()
        try:
            sell_values = [t.value for t in SignalType if t.is_sell]
            existing = self.db.get_signal_tickers_for_day(signal_types=sell_values, day=today_tr)
        except Exception as exc:
            logger.exception("sat_dedup_lookup_failed", error=exc)
            existing = set()
        seen: set[str] = set(existing)
        kept: list[Signal] = []
        dropped = 0
        for s in signals:
            if s.signal_type.is_sell:
                if s.ticker in seen:
                    dropped += 1
                    continue
                seen.add(s.ticker)
            kept.append(s)
        if dropped:
            logger.info(
                "sat_dedup",
                dropped=dropped,
                day=str(today_tr),
                component="scanner",
            )
        return kept

    def _filter_duplicate_als(self, signals: list[Signal]) -> list[Signal]:
        """Drop AL (actionable buy) signals whose ticker produced another
        actionable buy-family signal within the cooldown window (default 60
        minutes). Persistence-only scope, mirroring _filter_duplicate_sats:
        notifications, paper trades, and outcome tracking still see the full
        list, which is what the user asked: no AL spam per ticker per hour.

        DB-backed (survives restarts): looks up the latest persisted
        buy-family signal timestamp per ticker within the window. Within the
        same batch, the first AL signal per ticker wins and later ones are
        dropped.
        """
        cooldown_minutes = int(getattr(self.settings, "AL_SIGNAL_COOLDOWN_MINUTES", 60))
        if cooldown_minutes <= 0:
            return signals
        al_candidates = [
            s for s in signals if s.signal_type.is_buy and categorize_signal(s) is SignalCategory.AL
        ]
        if not al_candidates:
            return signals
        # Identity-keyed: Signal is a dataclass (value-equality); two distinct
        # AL signals with identical fields must not compare equal here.
        al_ids: set[int] = {id(s) for s in al_candidates}

        now = datetime.now(UTC)
        since = now - timedelta(minutes=cooldown_minutes)
        buy_values = [t.value for t in SignalType if t.is_buy]
        # Only actionable persists arm the cooldown: RADAR/WEAK_BUY persists
        # (score below the buy threshold) must not suppress a fresh AL.
        # Guarded for injected third-party SignalChangeService stubs that do
        # not expose StrategyParams — fall back to the canonical default.
        change_service_params = getattr(self.signal_change_service, "params", None)
        if change_service_params is None:
            change_service_params = StrategyParams.from_settings()
        buy_threshold = float(change_service_params.buy_threshold)
        try:
            recent = self.db.get_last_signal_times(
                tickers=sorted({s.ticker for s in al_candidates}),
                signal_types=buy_values,
                since=since,
                min_score=buy_threshold,
            )
        except Exception as exc:
            logger.exception("al_cooldown_lookup_failed", error=exc)
            recent = {}

        seen: set[str] = set()
        kept: list[Signal] = []
        dropped = 0
        for s in signals:
            if id(s) in al_ids:
                ticker = s.ticker
                in_db = ticker in recent
                in_batch = ticker in seen
                if in_db or in_batch:
                    dropped += 1
                    continue
                seen.add(ticker)
            kept.append(s)
        if dropped:
            logger.info(
                "al_cooldown",
                dropped=dropped,
                cooldown_minutes=cooldown_minutes,
                component="scanner",
            )
        return kept

    def _process_signal_outcomes(self, signals: list[Signal], market_data: dict) -> None:
        """Run outcome tracking for AL signals (shadow pattern, isolated)."""
        try:
            self.signal_outcome_tracker.process_scan(signals, market_data)
        except Exception as exc:
            logger.exception("signal_outcome_processing_failed", error=exc)

    def scan_once(
        self,
        force_refresh: bool = False,
        abort_event: threading.Event | None = None,
    ) -> list[Signal]:
        """Run one complete scan and return all generated signals.

        When `force_refresh` is true, intraday fetch and analysis caches are
        invalidated before data loading. Only actionable signals are persisted
        and queued for execution/paper trading, but the full signal list is
        returned to callers for UI and diagnostics.

        If `abort_event` is provided and signaled, processing is aborted at phase
        boundaries to ensure strict discard of stale results without side-effects.
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

            # Phase boundary 1: Check abort after data loading and freshness checks
            if abort_event is not None and abort_event.is_set():
                logger.warning("scan_aborted_after_fetch", reason="timeout_or_cancellation")
                raise ScanAbortedError("Scan aborted after data fetch")

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

            # Phase boundary 2: Strict discard check before writing side effects / persisting signals
            if abort_event is not None and abort_event.is_set():
                logger.warning("scan_aborted_before_persistence", reason="timeout_or_cancellation")
                raise ScanAbortedError("Scan aborted before persistence (strict discard)")

            self._check_signal_changes(signals)
            persisted = self._filter_duplicate_sats(signals)
            persisted = self._filter_duplicate_als(persisted)
            self.db.save_signals(persisted)
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
            # Phase boundary 3: Check before notifying
            if abort_event is not None and abort_event.is_set():
                logger.warning("scan_aborted_before_notification", reason="timeout_or_cancellation")
                raise ScanAbortedError("Scan aborted before notification")

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
    def _last_bar_age_minutes(
        df: pd.DataFrame | None, *, interval: str | None = None
    ) -> float | None:
        """Age of the newest bar in minutes; None when undeterminable.

        Intraday bars are measured from the bar *close* (start + interval):
        bar timestamps are open-times, so a freshly-forming 15m candle is
        already 0-15 min "old" by start-time and Yahoo's ~15-20 min BIST feed
        delay would otherwise trip the gate on healthy data. Daily-or-slower
        bars are judged per session: the current trading day's bar counts as
        fresh (it only finalizes after the close); older sessions are stale.
        """
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
        ts = ts.tz_convert("UTC")
        now = pd.Timestamp.now(tz="UTC")
        bar_minutes = _interval_minutes(interval)
        if bar_minutes is None:
            return (now - ts).total_seconds() / 60.0
        if bar_minutes >= 24 * 60:
            bar_day = ts.tz_convert(TR).date()
            today = now.tz_convert(TR).date()
            if bar_day >= today:
                return 0.0
            return (now - ts).total_seconds() / 60.0
        bar_close = ts + pd.Timedelta(minutes=bar_minutes)
        return (now - bar_close).total_seconds() / 60.0

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
        trigger_interval = str(getattr(self.settings, "MTF_TRIGGER_INTERVAL", "15m") or "15m")
        for ticker, frames in all_data.items():
            trigger_df = frames.get("trigger") if isinstance(frames, dict) else None
            age = self._last_bar_age_minutes(trigger_df, interval=trigger_interval)
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
            # Throttle the halt alert — without it every aborted scan re-sends
            # the same Telegram message (scan cadence ~15 min).
            cooldown_min = float(getattr(self.settings, "STALE_HALT_ALERT_COOLDOWN_MINUTES", 120))
            now_utc = datetime.now(UTC)
            last_alert = getattr(self, "_last_stale_halt_alert_at", None)
            if last_alert is None or (now_utc - last_alert).total_seconds() >= cooldown_min * 60:
                self._last_stale_halt_alert_at = now_utc
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
