"""Scan orchestration service shared by CLI and dashboard flows."""

import logging
from datetime import datetime
from typing import Any, cast

from bist_bot.config.settings import settings as default_settings
from bist_bot.locales import get_message
from bist_bot.services.execution_service import ExecutionService
from bist_bot.services.notification_service import NotificationDispatchService
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.services.signal_change_service import SignalChangeService
from bist_bot.strategy.signal_models import Signal, SignalType


logger = logging.getLogger(__name__)


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
    ):
        """Compose fetch, analyze, persistence, and notification steps."""
        self.fetcher = fetcher
        self.engine = engine
        self.notifier = notifier
        self.db = db
        self.broker = broker
        self.settings = settings or default_settings
        self.signal_change_service = signal_change_service or SignalChangeService(db, notifier)
        self.execution_service = execution_service or ExecutionService(db, broker=broker, settings=self.settings)
        self.paper_trade_service = paper_trade_service or PaperTradeService(fetcher, db, settings=self.settings)
        self.notification_service = notification_service or NotificationDispatchService(notifier, settings=self.settings)

    def _auto_execute_signals(self, signals: list[Signal]) -> None:
        self.execution_service.auto_execute_signals(signals)

    def _check_signal_changes(self, signals: list[Signal]) -> None:
        self.signal_change_service.check_signal_changes(signals)

    def scan_once(self, force_refresh: bool = False) -> list:
        logger.info("\n" + "█" * 55)
        logger.info("█  " + get_message("log.scan_starting"))
        logger.info(f"█  Saat: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        logger.info(get_message("log.scanning_stocks", count=len(self.settings.WATCHLIST)))
        logger.info("█" * 55)

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

        if not all_data:
            logger.error("❌ " + get_message("log.data_fetch_failed"))
            return []

        logger.info("\n🧠 " + get_message("log.running_strategy"))
        signals = self.engine.scan_all(all_data)

        actionable = self.engine.get_actionable_signals(signals)

        buys = [s for s in signals if s.score > 0]
        sells = [s for s in signals if s.score < 0]

        logger.info(f"\n{'─'*55}")
        logger.info("📊 " + get_message("log.results"))
        logger.info(f"  {get_message('log.scanned')}: {len(all_data)}")
        logger.info(f"  {get_message('log.buy_signal')}: {len(buys)}")
        logger.info(f"  {get_message('log.sell_signal')}: {len(sells)}")
        logger.info(f"  {get_message('log.actionable')}: {len(actionable)}")
        logger.info(f"{'─'*55}")

        for s in signals:
            if s.signal_type not in (SignalType.HOLD,):
                print(s)

        self._check_signal_changes(signals)

        self.db.save_signals(actionable)
        self._auto_execute_signals(actionable)

        self.paper_trade_service.queue_actionable_signals(actionable)

        self.db.save_scan_log(
            len(all_data), len(actionable),
            len(buys), len(sells)
        )

        self.notification_service.notify_scan_results(signals, actionable, len(all_data))

        if getattr(self.settings, "PAPER_MODE", False):
            self.update_paper_trades()

        return cast(list[Signal], signals)

    def update_paper_trades(self):
        self.paper_trade_service.update_open_trades()
