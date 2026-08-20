"""Tests for confluence sell soft-fail behavior and is_actionable recomputation."""

from unittest.mock import MagicMock

from bist_bot.strategy.engine import StrategyEngine
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MarketRegime, TrendBias
from bist_bot.strategy.signal_models import Signal, SignalType


def test_confluence_short_with_neutral_bias_returns_hold():
    params = StrategyParams.conservative()
    engine = StrategyEngine(params=params)

    signal = Signal(
        ticker="GARAN.IS",
        signal_type=SignalType.SELL,
        score=-30.0,
        price=100.0,
        reasons=[],
        buy_threshold=params.buy_threshold,
        sell_threshold=params.sell_threshold,
    )

    # With TrendBias.NEUTRAL and a negative score (-30), evaluate_confluence must return HOLD
    result = engine._evaluate_confluence(
        ticker="GARAN.IS",
        signal=signal,
        trend_bias=TrendBias.NEUTRAL,
        multi_timeframe=True,
        trigger_candle_count=50,
    )
    assert result == SignalType.HOLD


def test_confluence_positive_with_neutral_bias_returns_radar():
    params = StrategyParams.conservative()
    engine = StrategyEngine(params=params)

    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=300.0,
        reasons=[],
        buy_threshold=params.buy_threshold,
        sell_threshold=params.sell_threshold,
    )

    # Positive score >= BUY_THRESHOLD with NEUTRAL bias should soft-fail to RADAR
    result = engine._evaluate_confluence(
        ticker="THYAO.IS",
        signal=signal,
        trend_bias=TrendBias.NEUTRAL,
        multi_timeframe=True,
        trigger_candle_count=50,
    )
    assert result == SignalType.RADAR


def test_macro_regime_gate_recomputes_is_actionable():
    params = StrategyParams.conservative()
    engine = StrategyEngine(params=params)

    # A BUY signal with score 30 and initial is_actionable=True
    sig = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=60.0,
        buy_threshold=25.0,
        is_actionable=True,
    )

    engine._detect_macro_regime = MagicMock(return_value=MarketRegime.BEAR)

    signals = [sig]
    engine._apply_macro_regime_gate(signals, data={})

    assert sig.signal_type == SignalType.RADAR
    # After demotion to RADAR, is_actionable must be recomputed to False!
    assert sig.is_actionable is False
