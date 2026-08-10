"""Tests for the macro regime gate wired into StrategyEngine.scan_all."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.strategy.engine import StrategyEngine
from bist_bot.strategy.regime import MACRO_BENCHMARK_TICKERS, MarketRegime
from bist_bot.strategy.signal_models import Signal, SignalType


def _frame(rows: int = 60) -> pd.DataFrame:
    n = rows
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(100, 150, n)
    return pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=dates,
    )


def _benchmark_data(rows: int = 60) -> dict[str, dict[str, pd.DataFrame]]:
    frame = _frame(rows)
    return {
        ticker: {"trend": frame.copy(), "trigger": frame.copy()}
        for ticker in MACRO_BENCHMARK_TICKERS
    }


@pytest.fixture()
def engine() -> StrategyEngine:
    return StrategyEngine()


def test_gate_demotes_buy_family_to_radar_in_bear(engine: StrategyEngine) -> None:
    signals = [
        Signal(ticker="X.IS", signal_type=SignalType.BUY, score=50, price=10.0),
        Signal(ticker="Y.IS", signal_type=SignalType.STRONG_BUY, score=70, price=10.0),
        Signal(ticker="Z.IS", signal_type=SignalType.WEAK_BUY, score=10, price=10.0),
        Signal(ticker="W.IS", signal_type=SignalType.SELL, score=-40, price=10.0),
    ]
    with patch(
        "bist_bot.strategy.engine.detect_macro_regime", return_value=MarketRegime.BEAR
    ):
        engine._apply_macro_regime_gate(signals, _benchmark_data())

    assert [s.signal_type for s in signals] == [
        SignalType.RADAR,
        SignalType.RADAR,
        SignalType.RADAR,
        SignalType.SELL,
    ]
    assert "Makro rejim BEAR" in signals[0].reasons[-1]
    assert engine.last_macro_regime == MarketRegime.BEAR


def test_gate_noop_when_regime_not_bear(engine: StrategyEngine) -> None:
    for regime in (MarketRegime.BULL, MarketRegime.SIDEWAYS, MarketRegime.UNKNOWN):
        signal = Signal(ticker="X.IS", signal_type=SignalType.BUY, score=50, price=10.0)
        with patch(
            "bist_bot.strategy.engine.detect_macro_regime", return_value=regime
        ):
            engine._apply_macro_regime_gate([signal], _benchmark_data())
        assert signal.signal_type == SignalType.BUY
        assert engine.last_macro_regime == regime


def test_gate_respects_disabled_setting(engine: StrategyEngine) -> None:
    signal = Signal(ticker="X.IS", signal_type=SignalType.BUY, score=50, price=10.0)
    with settings.override(MACRO_REGIME_GATE_ENABLED=False):
        with patch(
            "bist_bot.strategy.engine.detect_macro_regime", return_value=MarketRegime.BEAR
        ):
            engine._apply_macro_regime_gate([signal], _benchmark_data())
    assert signal.signal_type == SignalType.BUY
    assert engine.last_macro_regime == MarketRegime.UNKNOWN


def test_gate_noop_when_benchmark_data_missing(engine: StrategyEngine) -> None:
    """Short/non-benchmark data degrades to UNKNOWN → no demotion."""
    signal = Signal(ticker="PASS.IS", signal_type=SignalType.BUY, score=50, price=10.0)
    data = {
        "PASS.IS": {"trend": _frame(10), "trigger": _frame(10)},
        "THYAO.IS": {"trend": _frame(10), "trigger": _frame(10)},
    }
    engine._apply_macro_regime_gate([signal], data)
    assert signal.signal_type == SignalType.BUY
    assert engine.last_macro_regime == MarketRegime.UNKNOWN


def test_scan_all_applies_gate_to_generated_signals(engine: StrategyEngine) -> None:
    data = _benchmark_data()
    data["PASS.IS"] = {"trend": _frame(60), "trigger": _frame(60)}

    def _fake_analyze(ticker, df, enforce_sector_limit=True):
        return Signal(ticker=ticker, signal_type=SignalType.BUY, score=50, price=10.0)

    with (
        patch.object(engine, "analyze", side_effect=_fake_analyze),
        patch(
            "bist_bot.strategy.engine.detect_macro_regime", return_value=MarketRegime.BEAR
        ),
    ):
        signals = engine.scan_all(data)

    assert len(signals) == 4  # 3 benchmark + 1 PASS.IS
    assert all(s.signal_type == SignalType.RADAR for s in signals)
    assert all(any("Makro rejim BEAR" in r for r in s.reasons) for s in signals)