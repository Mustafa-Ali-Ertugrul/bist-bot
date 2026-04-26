"""Notification dispatch helpers for completed scans."""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings

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

    def notify_scan_results(self, signals, actionable, total_scanned: int) -> None:
        if not actionable:
            return

        self.notifier.send_scan_summary(signals, total_scanned)
        min_score = getattr(self.settings, "TELEGRAM_MIN_SCORE", 48)
        strong = [signal for signal in actionable if abs(signal.score) >= min_score]
        for signal in strong:
            if hasattr(signal, "is_expired") and signal.is_expired():
                logger.info(
                    "signal_expired_skipped",
                    ticker=signal.ticker,
                    score=signal.score,
                )
                continue
            self.notifier.send_signal(signal)
            self.sleeper(1)
