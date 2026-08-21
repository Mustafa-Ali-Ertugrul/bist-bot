"""Notification dispatch helpers for completed scans."""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.config.watchlist import load_watchlist
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
        # Load robust watchlist once at startup; membership check is O(1).
        self._robust_set: set[str] = set(load_watchlist("robust"))
        self._group_chat_id = getattr(self.settings, "TELEGRAM_GROUP_CHAT_ID", "") or None
        self._batch_threshold = getattr(self.settings, "TELEGRAM_GROUP_BATCH_THRESHOLD", 5)

    def _is_robust_member(self, signal) -> bool:
        return signal.ticker in self._robust_set

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

        # Mirror the scan summary to the group (single informative message).
        self.notifier.send_scan_summary_to_group(signals, total_scanned)

        # Group detail routing is protected by the robust watchlist: only
        # H6-ON robust members get detail messages, so overfit names that
        # failed the stress test never reach the public channel.
        robust_details = [s for s in detail_signals if self._is_robust_member(s)]
        if not robust_details:
            return

        # Batch protection: when there are too many robust signals, send one
        # compact summary instead of spamming individual detail messages.
        if len(robust_details) > self._batch_threshold:
            self._send_group_batch_summary(robust_details)
            return

        for signal in robust_details:
            self.notifier.send_signal_to_group(signal)
            self.sleeper(1)

    def _send_group_batch_summary(self, signals: list) -> None:
        lines = [f"🔔 <b>Grup Özet — {len(signals)} robust sinyal</b>"]
        for s in signals:
            cat = categorize_signal(s)
            label = "🟢 AL" if cat is SignalCategory.AL else "👁️ İZLE"
            lines.append(f"  {label} {s.ticker} (Skor: {s.score:+.0f})")
        self.notifier.send_to_group("\n".join(lines))
