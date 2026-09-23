"""Unit and integration tests for AlphaTrendStrategy."""

from datetime import datetime

import numpy as np
import pandas as pd

from bist_bot.strategy.alpha_trend import AlphaTrendStrategy
from bist_bot.strategy.signal_models import SignalType


def make_sample_ohlcv(n: int = 100, trend: float = 0.5, volume_surge: bool = False) -> pd.DataFrame:
    dates = pd.date_range(datetime(2024, 1, 1), periods=n, freq="D")
    base = 100.0 + np.arange(n) * trend
    volumes = np.full(n, 10_000.0)
    if volume_surge:
        volumes[-1] = 25_000.0  # 2.5x volume

    highs = base + 2.0
    lows = base - 2.0
    opens = base - 0.5
    closes = base + 1.5  # close near high

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    return df


def test_alpha_trend_triggers_on_valid_setup():
    xu100 = make_sample_ohlcv(100, trend=0.2)
    stock = make_sample_ohlcv(100, trend=0.8, volume_surge=True)
    # Ensure last bar is a 20-day high breakout
    stock.iloc[-1, stock.columns.get_loc("close")] = stock["high"].iloc[-21:-1].max() + 1.0
    stock.iloc[-1, stock.columns.get_loc("high")] = stock.iloc[-1]["close"] + 0.2

    strat = AlphaTrendStrategy()
    strat.set_benchmark(xu100)

    sig = strat.analyze("TEST.IS", stock)
    assert sig is not None
    assert sig.ticker == "TEST.IS"
    assert sig.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
    assert sig.score >= 25.0
    assert sig.is_actionable is True
    assert sig.stop_loss < sig.price
    assert sig.target_price > sig.price
    assert any("Göreceli Güç" in r for r in sig.reasons)
    assert any("Kurumsal Hacim" in r for r in sig.reasons)


def test_alpha_trend_blocks_when_benchmark_bearish():
    # Benchmark in downtrend
    xu100 = make_sample_ohlcv(100, trend=-0.5)
    stock = make_sample_ohlcv(100, trend=0.8, volume_surge=True)

    strat = AlphaTrendStrategy()
    strat.set_benchmark(xu100)

    sig = strat.analyze("TEST.IS", stock)
    # Must block when index is falling
    assert sig is None


def test_alpha_trend_blocks_without_volume_surge():
    xu100 = make_sample_ohlcv(100, trend=0.2)
    stock = make_sample_ohlcv(100, trend=0.8, volume_surge=False)  # normal volume

    strat = AlphaTrendStrategy()
    strat.set_benchmark(xu100)

    sig = strat.analyze("TEST.IS", stock)
    assert sig is None


def test_alpha_trend_raw_benchmark_via_constructor_computes_gate():
    """Constructor'a ham benchmark geçilirse kapı sütunları otomatik hesaplanır."""
    xu100 = make_sample_ohlcv(100, trend=0.2)
    stock = make_sample_ohlcv(100, trend=0.8, volume_surge=True)
    # Ensure last bar is a 20-day high breakout
    stock.iloc[-1, stock.columns.get_loc("close")] = stock["high"].iloc[-21:-1].max() + 1.0
    stock.iloc[-1, stock.columns.get_loc("high")] = stock.iloc[-1]["close"] + 0.2

    # set_benchmark ÇAĞRILMADI — ham df doğrudan constructor'a verildi.
    strat = AlphaTrendStrategy(xu100_df=xu100)

    sig = strat.analyze("TEST.IS", stock)
    # Bullish benchmark + geçerli setup → sinyal üretilmeli (kapı hesaplandı).
    assert sig is not None
    assert sig.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)


def test_alpha_trend_bearish_raw_benchmark_via_constructor_blocks():
    """Ham benchmark düşüşteyse constructor yoluyla da kapı kapatılmalı."""
    xu100 = make_sample_ohlcv(100, trend=-0.5)
    stock = make_sample_ohlcv(100, trend=0.8, volume_surge=True)

    strat = AlphaTrendStrategy(xu100_df=xu100)

    sig = strat.analyze("TEST.IS", stock)
    assert sig is None


def test_alpha_trend_gate_fails_closed_without_is_bullish_column():
    """Fail-closed savunması: is_bullish sütunu yoksa sinyal üretilmez.

    set_benchmark atlanıp xu100_df doğrudan atandıysa (eski fail-open yolu)
    artık varsayılan True değil False ile kapanır.
    """
    xu100 = make_sample_ohlcv(100, trend=0.2)  # bullish trend
    stock = make_sample_ohlcv(100, trend=0.8, volume_surge=True)

    strat = AlphaTrendStrategy()
    strat.xu100_df = xu100  # set_benchmark ATLANDI → is_bullish sütunu yok

    sig = strat.analyze("TEST.IS", stock)
    # Fail-closed: sütun eksikse kapı kapalı sayılır → sinyal yok.
    assert sig is None
