"""Notification dispatch helpers for completed scans.

Faz 0b (2026-10-21): group mirroring is gone. Signals are an internal
research tool; the customer group must not receive buy/sell messages with
stop/target levels. A per-user digest will return in a later phase, built on
``NotifierProtocol.send_to_group`` and an explicit opt-in.
"""

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

    def notify_scan_results(self, signals, actionable, total_scanned: int) -> None:
        """Send the scan summary and detail messages to the operator only."""
        if not signals:
            return

        self.notifier.send_scan_summary(signals, total_scanned)

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
            self.notifier.send_signal(signal)
            self.sleeper(1)
