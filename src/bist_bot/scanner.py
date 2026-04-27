"""Scan orchestration service shared by CLI and dashboard flows."""

import time
from typing import Any, cast

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter, set_gauge
from bist_bot.config.settings import settings as default_settings
from bist_bot.services.execution_service import ExecutionService
from bist_bot.services.notification_service import NotificationDispatchService
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.services.signal_change_service import SignalChangeService
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="scanner")


class ScanService:
    def __init__(
        self,
        fetcher,
        engine,
        notifier,
        db,
        broker=None,
        settings: Any | None = None,
        signal_change_service: SignalChangeService | None = None,
        execution_service: ExecutionService | None = None,
        paper_trade_service: PaperTradeService | None = None,
        notification_service: NotificationDispatchService | None = None,
        circuit_breaker=None,
    ):
        """Compose fetch, analyze, persistence, and notification steps."""
        self.fetcher = fetcher
        self.engine = engine
        self.notifier = notifier
        self.db = db
        self.broker = broker
        self.settings = settings or default_settings
        self.signal_change_service = signal_change_service or SignalChangeService(
            db, notifier
        )
        self.execution_service = execution_service or ExecutionService(
            db, broker=broker, settings=self.settings
        )
        self.paper_trade_service = paper_trade_service or PaperTradeService(
            fetcher, db, settings=self.settings
        )
        self.notification_service = notification_service or NotificationDispatchService(
            notifier, settings=self.settings
        )
        self.circuit_breaker = circuit_breaker
        self.last_scan_stats: dict[str, int] = {
            "scanned": 0,
            "actionable": 0,
            "buys": 0,
            "sells": 0,
        }

    def _auto_execute_signals(
        self, signals: list[Signal], auto_execute: bool | None = None
    ) -> None:
        self.execution_service.auto_execute_signals(signals, auto_execute=auto_execute)

    def _check_signal_changes(self, signals: list[Signal]) -> None:
        self.signal_change_service.check_signal_changes(signals)

    def scan_once(
        self,
        force_refresh: bool = False,
        limit: int | None = None,
        paper_mode: bool | None = None,
        auto_execute: bool | None = None,
    ) -> list:
        started_at = time.perf_counter()
        watchlist = self.settings.WATCHLIST
        if limit is not None and limit > 0:
            watchlist = watchlist[:limit]
        logger.info("scan_started", scanned_count=len(watchlist), component="scanner")

        try:
            if (
                self.circuit_breaker is not None
                and not self.circuit_breaker.allow_request()
            ):
                logger.warning("scan_aborted_circuit_open", component="scanner")
                return []

            if force_refresh:
                self.fetcher.clear_cache(scope="intraday_fetch")
                self.fetcher.clear_cache(scope="analysis")
            all_data = self.fetcher.fetch_multi_timeframe_all(
                trend_period=getattr(self.settings, "MTF_TREND_PERIOD", "6mo"),
                trend_interval=getattr(self.settings, "MTF_TREND_INTERVAL", "1d"),
                trigger_period=getattr(self.settings, "MTF_TRIGGER_PERIOD", "1mo"),
                trigger_interval=getattr(self.settings, "MTF_TRIGGER_INTERVAL", "15m"),
                force_refresh=force_refresh,
                limit=limit,
            )

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
            actionable = self.engine.get_actionable_signals(signals)
            buys = [s for s in signals if s.score > 0]
            sells = [s for s in signals if s.score < 0]
            self.last_scan_stats = {
                "scanned": len(all_data),
                "actionable": len(actionable),
                "buys": len(buys),
                "sells": len(sells),
            }

            self._check_signal_changes(signals)
            self.db.save_signals(signals)
            self._auto_execute_signals(actionable, auto_execute=auto_execute)
            self.paper_trade_service.queue_actionable_signals(
                actionable, paper_mode=paper_mode
            )
            self.db.save_scan_log(len(all_data), len(actionable), len(buys), len(sells))
            self.notification_service.notify_scan_results(
                signals, actionable, len(all_data)
            )

            self.update_paper_trades(paper_mode=paper_mode)

            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            inc_counter("bist_scan_total")
            inc_counter("bist_signal_emitted_total", len(actionable))
            set_gauge("bist_last_scan_duration_ms", duration_ms)
            set_gauge("bist_last_scan_scanned_count", len(all_data))
            logger.info(
                "scan_completed",
                duration_ms=duration_ms,
                scanned_count=len(all_data),
                actionable_count=len(actionable),
            )

            for signal in signals:
                if signal.signal_type is not SignalType.HOLD:
                    logger.info(
                        "signal_emitted",
                        ticker=signal.ticker,
                        signal_type=signal.signal_type.value,
                        score=signal.score,
                        price=signal.price,
                    )

            if self.circuit_breaker is not None:
                self.circuit_breaker.record_success()

            return cast(list[Signal], signals)
        except Exception as exc:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_error()
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            inc_counter("bist_scan_fail_total")
            set_gauge("bist_last_scan_duration_ms", duration_ms)
            logger.exception("scan_failed", error=exc, duration_ms=duration_ms)
            raise

    def update_paper_trades(self, paper_mode: bool | None = None):
        if paper_mode is None:
            paper_mode = getattr(self.settings, "PAPER_MODE", False)
        if not paper_mode:
            return
        self.paper_trade_service.update_open_trades()
