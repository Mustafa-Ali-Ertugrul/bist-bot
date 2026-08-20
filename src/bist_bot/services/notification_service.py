"""Notification dispatch helpers for completed scans."""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.strategy.signal_models import SignalCategory, categorize_signal

logger = get_logger(__name__, component="notification")


class NotificationDispatchService:
    def __init__(
        self,
        notifier,
        settings: Any | None = None,
        sleeper: Callable[[float], None] = default_sleep,
    ) -> None:
        self.notifier = notifier
        self.settings = settings or default_settings
        self.sleeper = sleeper
        self._group_chat_id = getattr(self.settings, "TELEGRAM_GROUP_CHAT_ID", "") or None

    def notify_scan_results(self, signals, actionable, total_scanned: int) -> None:
        if not signals:
            return

        self.notifier.send_scan_summary(signals, total_scanned)

        detail_signals = []
        for signal in signals:
            # AL signals always get detail messages.
            # Positive RADAR signals also get detail messages (with "RADAR / İZLE" label)
            # so the owner can track near-threshold names.  SAT/HOLD do not.
            cat = categorize_signal(signal)
            if cat is SignalCategory.AL:
                pass  # always include
            elif cat is SignalCategory.RADAR and signal.score > 0:
                pass  # positive radar — include with radar label
            else:
                continue
            if hasattr(signal, "is_expired") and signal.is_expired():
                logger.info("signal_expired_skipped", ticker=signal.ticker, score=signal.score)
                continue
            detail_signals.append(signal)
            self.notifier.send_signal(signal)
            self.sleeper(1)

        if not self._group_chat_id:
            return

        # Mirror the owner's complete scan notification set to the group.
        # No watchlist, score-threshold, or batch filter is applied here.
        self.notifier.send_scan_summary_to_group(signals, total_scanned)
        for signal in detail_signals:
            self.notifier.send_signal_to_group(signal)
            self.sleeper(1)
