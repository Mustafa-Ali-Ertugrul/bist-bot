"""Notification dispatch helpers for completed scans."""

from __future__ import annotations

from time import sleep as default_sleep
from typing import Any, Callable

from bist_bot.config.settings import settings as default_settings


class NotificationDispatchService:
    def __init__(self, notifier, settings: Any | None = None, sleeper: Callable[[float], None] = default_sleep) -> None:
        self.notifier = notifier
        self.settings = settings or default_settings
        self.sleeper = sleeper

    def notify_scan_results(self, signals, actionable, total_scanned: int) -> None:
        if not actionable:
            return

        self.notifier.send_scan_summary(signals, total_scanned)
        strong = [
            signal
            for signal in actionable
            if abs(signal.score) >= getattr(self.settings, "TELEGRAM_MIN_SCORE", 70)
        ]
        for signal in strong:
            self.notifier.send_signal(signal)
            self.sleeper(1)
