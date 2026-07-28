"""Notification dispatch helpers for completed scans."""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.config.watchlist import load_watchlist

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
        self._group_chat_id = (
            getattr(self.settings, "TELEGRAM_GROUP_CHAT_ID", "") or None
        )
        self._batch_threshold = getattr(
            self.settings, "TELEGRAM_GROUP_BATCH_THRESHOLD", 5
        )

    def _is_robust_member(self, signal) -> bool:
        return signal.ticker in self._robust_set

    def notify_scan_results(self, signals, actionable, total_scanned: int) -> None:
        if not signals:
            return

        self.notifier.send_scan_summary(signals, total_scanned)

        # Detail messages for all positive-score signals (actionable + radar).
        # Previously gated by score threshold; now expanded to any signal that
        # scored above zero so the radar / izle label reaches the owner.
        for signal in signals:
            if signal.score <= 0:
                continue
            if hasattr(signal, "is_expired") and signal.is_expired():
                logger.info(
                    "signal_expired_skipped",
                    ticker=signal.ticker,
                    score=signal.score,
                )
                continue

            self.notifier.send_signal(signal)
            self.sleeper(1)

        # Group dispatch: robust-watchlist membership replaces the old
        # TELEGRAM_GROUP_MIN_SCORE score gate.  TELEGRAM_GROUP_MIN_SCORE is
        # kept in settings for backward compatibility but is no longer used
        # as a routing gate — it is deprecated (see subserSettings.py).
        if not self._group_chat_id:
            return

        # Gather all positive-score signals that are robust members.
        robust_positive = [
            s for s in signals
            if s.score > 0 and self._is_robust_member(s)
        ]

        if not robust_positive:
            return

        # Batch protection: if there are enough robust signals, send one
        # summary rather than individual messages.
        if len(robust_positive) > self._batch_threshold:
            self._send_group_batch_summary(robust_positive)
        else:
            for signal in robust_positive:
                label = (
                    "🟢 AL (robust üye)"
                    if signal.is_actionable
                    else "👁️ İZLE (robust üye, eşik altı)"
                )
                stop = (
                    f" | Stop: ₺{signal.stop_loss:.2f}"
                    if signal.stop_loss
                    else ""
                )
                target = (
                    f" | Hedef: ₺{signal.target_price:.2f}"
                    if signal.target_price
                    else ""
                )
                self.notifier.send_to_group(
                    f"{label} — {signal.ticker} "
                    f"(Skor: {signal.score:+.0f}{stop}{target})"
                )
                self.sleeper(1)

    def _send_group_batch_summary(self, signals: list) -> None:
        lines = [
            f"🔔 <b>Grup Özet — {len(signals)} sinyal</b>",
        ]
        for s in signals:
            label = (
                "🟢 AL"
                if s.is_actionable
                else "👁️ İZLE"
            )
            lines.append(
                f"  {label} {s.ticker} (Skor: {s.score:+.0f})"
            )
        self.notifier.send_to_group("\n".join(lines))
