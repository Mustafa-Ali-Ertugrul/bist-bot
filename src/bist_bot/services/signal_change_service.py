"""Signal change detection and notification helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep as default_sleep

from bist_bot.app_logging import get_logger
from bist_bot.strategy.engine_filters import is_trade_actionable
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="signal_change")

MIN_SCORE_DELTA_RANGE = (0.0, 100.0)


def _normalize_min_score_delta(value: float | None) -> float:
    """Clamp the user-facing notification threshold into the valid 0-100 range."""
    if value is None:
        value = 0.0
    try:
        delta = float(value)
    except (TypeError, ValueError):
        delta = 0.0
    low, high = MIN_SCORE_DELTA_RANGE
    return max(low, min(high, delta))


class SignalChangeService:
    """Detect signal-type changes and optionally notify the user.

    Every signal-type change is logged, but a user-facing notification is
    only sent when the change carries trading intent — i.e. when either the
    old or the new signal is trade-actionable — or when the score moved by at
    least ``min_score_delta`` points. Small, non-actionable oscillations
    (e.g. SELL -> WEAK_SELL -> SELL noise) are suppressed to keep Telegram
    traffic meaningful. ``min_score_delta=0`` restores the legacy behaviour
    of notifying on every signal-type change.
    """

    def __init__(
        self,
        db,
        notifier,
        *,
        sleeper: Callable[[float], None] = default_sleep,
        params: StrategyParams | None = None,
        min_score_delta: float | None = None,
    ) -> None:
        self.db = db
        self.notifier = notifier
        self.sleeper = sleeper
        self.params = params or StrategyParams.from_settings()
        self.min_score_delta = _normalize_min_score_delta(min_score_delta)

    def check_signal_changes(self, signals: list[Signal]) -> None:
        for signal in signals:
            previous = self.db.get_latest_signal(signal.ticker)
            if not previous:
                self._log_first_seen(signal)
                continue
            if previous["signal_type"] == signal.signal_type.value:
                continue

            old_signal = self._rebuild_previous_signal(signal, previous)
            if old_signal is None:
                continue

            old_actionable = is_trade_actionable(old_signal, self.params)
            new_actionable = is_trade_actionable(signal, self.params)
            score_delta = abs(float(signal.score) - float(old_signal.score))
            meaningful_change = (
                old_actionable or new_actionable or score_delta >= self.min_score_delta
            )
            self._log_signal_changed(
                old_signal=old_signal,
                new_signal=signal,
                old_actionable=old_actionable,
                new_actionable=new_actionable,
                score_delta=score_delta,
                notified=meaningful_change,
            )
            if not meaningful_change:
                continue

            self.notifier.send_signal_change(signal.ticker, old_signal, signal)
            self.sleeper(1)

    @staticmethod
    def _log_first_seen(signal: Signal) -> None:
        """Log a first observation for the ticker; never notifies here."""
        logger.debug(
            "signal_changed",
            ticker=signal.ticker,
            old_signal=None,
            new_signal=signal.signal_type.value,
            old_score=None,
            new_score=round(float(signal.score), 2),
            delta=None,
            notified=False,
            suppressed=False,
            gate="first_signal",
            suppress_reason="",
        )

    def _rebuild_previous_signal(self, signal: Signal, previous: dict) -> Signal | None:
        """Rebuild the stored Signal from the latest DB record.

        A malformed timestamp makes the change descriptor untrustworthy; the
        transition is skipped entirely (no notification) rather than sent with
        broken metadata.
        """
        raw_timestamp = previous.get("timestamp")
        if isinstance(raw_timestamp, datetime):
            dt_parsed = raw_timestamp
            if dt_parsed.tzinfo is None:
                dt_parsed = dt_parsed.replace(tzinfo=UTC)
        else:
            try:
                dt_parsed = datetime.fromisoformat(str(raw_timestamp or ""))
            except ValueError:
                logger.debug(
                    "signal_change_previous_timestamp_invalid",
                    ticker=signal.ticker,
                    timestamp=str(raw_timestamp or ""),
                )
                return None
            if dt_parsed.tzinfo is None:
                dt_parsed = dt_parsed.replace(tzinfo=UTC)

        return Signal(
            ticker=previous["ticker"],
            signal_type=SignalType(previous["signal_type"]),
            score=float(previous.get("score") or 0),
            price=previous["price"],
            stop_loss=previous.get("stop_loss", 0) or 0,
            target_price=previous.get("target_price", 0) or 0,
            position_size=previous.get("position_size"),
            confidence=previous.get("confidence", "confidence.low") or "confidence.low",
            timestamp=dt_parsed,
        )

    def _log_signal_changed(
        self,
        *,
        old_signal: Signal,
        new_signal: Signal,
        old_actionable: bool,
        new_actionable: bool,
        score_delta: float,
        notified: bool,
    ) -> None:
        """Log every detected signal-type change with gate diagnostics."""
        suppressed = not notified
        if notified and old_actionable and new_actionable:
            gate = "both_actionable"
        elif notified and old_actionable:
            gate = "old_actionable"
        elif notified and new_actionable:
            gate = "new_actionable"
        elif notified:
            gate = "score_delta"
        else:
            gate = "suppressed_non_actionable"
        suppress_reason = (
            ""
            if notified
            else (
                f"neither_signal_actionable;score_delta={abs(float(new_signal.score) - float(old_signal.score)):.2f}"
                f"<min_score_delta={self.min_score_delta:.2f}"
            )
        )
        logger.info(
            "signal_changed",
            ticker=new_signal.ticker,
            old_signal=old_signal.signal_type.value,
            new_signal=new_signal.signal_type.value,
            old_score=round(float(old_signal.score), 2),
            new_score=round(float(new_signal.score), 2),
            delta=round(score_delta, 2),
            notified=notified,
            suppressed=suppressed,
            gate=gate,
            suppress_reason=suppress_reason,
        )

