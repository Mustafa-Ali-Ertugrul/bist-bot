"""Signal change detection and notification helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from time import sleep as default_sleep

from bist_bot.app_logging import get_logger
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="signal_change")


class SignalChangeService:
    def __init__(self, db, notifier, sleeper: Callable[[float], None] = default_sleep) -> None:
        self.db = db
        self.notifier = notifier
        self.sleeper = sleeper

    def check_signal_changes(self, signals: list[Signal]) -> None:
        for signal in signals:
            previous = self.db.get_latest_signal(signal.ticker)
            if not previous or previous["signal_type"] == signal.signal_type.value:
                continue

            old_signal = Signal(
                ticker=previous["ticker"],
                signal_type=SignalType(previous["signal_type"]),
                score=previous["score"],
                price=previous["price"],
                stop_loss=previous.get("stop_loss", 0) or 0,
                target_price=previous.get("target_price", 0) or 0,
                position_size=previous.get("position_size"),
                confidence=previous.get("confidence", "confidence.low") or "confidence.low",
                timestamp=datetime.fromisoformat(previous["timestamp"]),
            )
            self.notifier.send_signal_change(signal.ticker, old_signal, signal)
            logger.info(
                "signal_changed",
                ticker=signal.ticker,
                old_signal=previous["signal_type"],
                new_signal=signal.signal_type.value,
            )
            self.sleeper(1)
