"""Benchmark iterative vs vectorized backtest execution on synthetic data."""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime
from time import perf_counter

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from bist_bot.backtest import Backtester  # noqa: E402


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class IterativeBacktester(Backtester):
    def _use_vectorized_path(self) -> bool:
        return False


def build_benchmark_frame(periods: int = 5000) -> pd.DataFrame:
    rows: list[dict[str, float | str | datetime]] = []
    dates = pd.date_range(datetime(2010, 1, 1), periods=periods, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 44
        base = 100.0 + idx * 0.08 + math.sin(idx / 11) * 3.0
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


def run_benchmark() -> None:
    df = build_benchmark_frame()
    vectorized = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    iterative = IterativeBacktester(initial_capital=10_000, indicators=IdentityIndicators())

    started = perf_counter()
    vectorized_result = vectorized.run("TEST.IS", df, verbose=False)
    vectorized_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    iterative_result = iterative.run("TEST.IS", df, verbose=False)
    iterative_ms = (perf_counter() - started) * 1000

    if vectorized_result is None or iterative_result is None:
        raise RuntimeError("Benchmark backtest returned no result")

    print(f"vectorized_ms={vectorized_ms:.2f}")
    print(f"iterative_ms={iterative_ms:.2f}")
    print(f"speedup_x={iterative_ms / vectorized_ms:.2f}")
    print(f"vectorized_final_capital={vectorized_result.final_capital:.2f}")
    print(f"iterative_final_capital={iterative_result.final_capital:.2f}")
    print(f"total_trades={vectorized_result.total_trades}")


if __name__ == "__main__":
    run_benchmark()
