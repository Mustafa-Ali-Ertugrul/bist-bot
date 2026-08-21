"""Tests for canonical SignalCategory and categorize/categorize_signal functions."""

from datetime import UTC, datetime

import pytest

from bist_bot.strategy.signal_models import (
    Signal,
    SignalCategory,
    SignalType,
    categorize,
    categorize_signal,
)


def _make_signal(
    signal_type: SignalType,
    score: float,
    buy_threshold: float = 25.0,
    is_actionable: bool = False,
) -> Signal:
    return Signal(
        ticker="THYAO.IS",
        signal_type=signal_type,
        score=score,
        price=300.0,
        buy_threshold=buy_threshold,
        is_actionable=is_actionable,
        timestamp=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    ("signal_type", "score", "buy_threshold", "expected"),
    [
        # Buy family - actionable
        (SignalType.STRONG_BUY, 50.0, 25.0, SignalCategory.AL),
        (SignalType.BUY, 25.0, 25.0, SignalCategory.AL),
        (SignalType.BUY, 30.0, 25.0, SignalCategory.AL),
        # Buy family - below threshold -> RADAR
        (SignalType.WEAK_BUY, 24.9, 25.0, SignalCategory.RADAR),
        (SignalType.WEAK_BUY, 8.0, 25.0, SignalCategory.RADAR),
        (SignalType.BUY, 20.0, 25.0, SignalCategory.RADAR),
        (SignalType.WEAK_BUY, 0.5, 25.0, SignalCategory.RADAR),
        # Buy family - zero / negative edge cases -> HOLD
        (SignalType.WEAK_BUY, 0.0, 25.0, SignalCategory.HOLD),
        (SignalType.WEAK_BUY, -5.0, 25.0, SignalCategory.HOLD),
        # RADAR type
        (SignalType.RADAR, 25.0, 25.0, SignalCategory.RADAR),
        (SignalType.RADAR, 15.0, 25.0, SignalCategory.RADAR),
        (SignalType.RADAR, 0.1, 25.0, SignalCategory.RADAR),
        (SignalType.RADAR, 0.0, 25.0, SignalCategory.HOLD),
        (SignalType.RADAR, -10.0, 25.0, SignalCategory.HOLD),
        # Sell family -> always SAT
        (SignalType.STRONG_SELL, -50.0, 25.0, SignalCategory.SAT),
        (SignalType.SELL, -25.0, 25.0, SignalCategory.SAT),
        (SignalType.WEAK_SELL, -15.0, 25.0, SignalCategory.SAT),
        (SignalType.WEAK_SELL, -8.0, 25.0, SignalCategory.SAT),
        (SignalType.WEAK_SELL, -0.5, 25.0, SignalCategory.SAT),
        # HOLD type
        (SignalType.HOLD, 0.0, 25.0, SignalCategory.HOLD),
        (SignalType.HOLD, 10.0, 25.0, SignalCategory.HOLD),
        (SignalType.HOLD, -10.0, 25.0, SignalCategory.HOLD),
    ],
)
def test_categorize_primitive(signal_type, score, buy_threshold, expected):
    assert categorize(signal_type, score, buy_threshold) == expected


def test_categorize_signal_uses_internal_threshold_and_ignores_stale_flag():
    # Stale is_actionable=True on a WEAK_BUY (score 20 < threshold 25)
    sig1 = _make_signal(SignalType.WEAK_BUY, score=20.0, buy_threshold=25.0, is_actionable=True)
    assert categorize_signal(sig1) == SignalCategory.RADAR

    # Stale is_actionable=False on a BUY (score 30 >= threshold 25)
    sig2 = _make_signal(SignalType.BUY, score=30.0, buy_threshold=25.0, is_actionable=False)
    assert categorize_signal(sig2) == SignalCategory.AL

    # Override threshold
    assert categorize_signal(sig1, buy_threshold=15.0) == SignalCategory.AL
