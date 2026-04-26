"""Regression coverage for vectorized backtest path."""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from bist_bot.backtest import Backtester


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class IterativeBacktester(Backtester):
    def _use_vectorized_path(self) -> bool:
        return False


def build_vectorized_regression_frame(periods: int = 220) -> pd.DataFrame:
    rows: list[dict[str, float | str | datetime]] = []
    dates = pd.date_range(datetime(2024, 1, 1), periods=periods, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 44
        base = 100.0 + idx * 0.35 + math.sin(idx / 6) * 2.5
        if phase < 8:
            rsi = 24.0
            sma_cross = "GOLDEN_CROSS" if phase == 0 else "NONE"
            macd_cross = "BULLISH"
            bb_position = "BELOW_LOWER"
            sma_fast = base + 2.0
            sma_slow = base - 1.5
        elif 22 <= phase < 30:
            rsi = 78.0
            sma_cross = "DEATH_CROSS" if phase == 22 else "NONE"
            macd_cross = "BEARISH"
            bb_position = "ABOVE_UPPER"
            sma_fast = base - 2.0
            sma_slow = base + 1.5
        else:
            rsi = 50.0
            sma_cross = "NONE"
            macd_cross = "NONE"
            bb_position = "MIDDLE"
            sma_fast = base + 0.5
            sma_slow = base

        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 2.5,
                "low": base - 2.5,
                "close": base + 0.6,
                "volume": 10_000,
                "volume_sma_20": 10_000,
                "atr": 2.0,
                "rsi": rsi,
                "sma_cross": sma_cross,
                "macd_cross": macd_cross,
                "bb_position": bb_position,
                "sma_5": sma_fast,
                "sma_20": sma_slow,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def test_vectorized_backtest_matches_iterative_within_tolerance() -> None:
    df = build_vectorized_regression_frame()
    vectorized = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    iterative = IterativeBacktester(initial_capital=10_000, indicators=IdentityIndicators())

    vectorized_result = vectorized.run("TEST.IS", df, verbose=False)
    iterative_result = iterative.run("TEST.IS", df, verbose=False)

    assert vectorized_result is not None
    assert iterative_result is not None
    assert vectorized_result.total_trades == iterative_result.total_trades
    assert vectorized_result.final_capital == iterative_result.final_capital
    assert abs(vectorized_result.total_return_pct - iterative_result.total_return_pct) <= 0.01
