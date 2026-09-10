"""Aşama 3: BACKTEST_FORCE_ITERATIVE yol seçimi testleri.

- Env yokken yol seçimi değişmez (mevcut koşul korunur).
- True iken iteratif yol zorlanır, False iken mevcut seçim korunur.
- Aynı veri + params ile iki yolun sonuç eşdeğerliği kontrol edilir.
  Mevcut bir yol farkı bulunursa gizlice düzeltilmez, ayrı hata raporlanır.
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from bist_bot.backtest import Backtester
from bist_bot.config.settings import settings


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


def _regression_frame(periods: int = 220) -> pd.DataFrame:
    rows: list[dict] = []
    dates = pd.date_range(datetime(2024, 1, 1), periods=periods, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 44
        base = 100.0 + idx * 0.35 + math.sin(idx / 6) * 2.5
        if phase < 8:
            rsi, sma_cross, macd_cross, bb_position = (
                24.0,
                ("GOLDEN_CROSS" if phase == 0 else "NONE"),
                "BULLISH",
                "BELOW_LOWER",
            )
            sma_fast, sma_slow = base + 2.0, base - 1.5
        elif 22 <= phase < 30:
            rsi, sma_cross, macd_cross, bb_position = (
                78.0,
                ("DEATH_CROSS" if phase == 22 else "NONE"),
                "BEARISH",
                "ABOVE_UPPER",
            )
            sma_fast, sma_slow = base - 2.0, base + 1.5
        else:
            rsi, sma_cross, macd_cross, bb_position = 50.0, "NONE", "NONE", "MIDDLE"
            sma_fast, sma_slow = base + 0.5, base
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


def test_path_selection_unchanged_without_env() -> None:
    bt = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    assert bt._use_vectorized_path() is True


def test_force_iterative_env_forces_iterative_path() -> None:
    with settings.override(BACKTEST_FORCE_ITERATIVE=True):
        bt = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
        assert bt._use_vectorized_path() is False


def test_force_iterative_false_keeps_existing_selection() -> None:
    with settings.override(BACKTEST_FORCE_ITERATIVE=False):
        bt = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
        assert bt._use_vectorized_path() is True


def test_both_paths_agree_on_same_data() -> None:
    df = _regression_frame()
    vectorized = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    assert vectorized._use_vectorized_path() is True
    vectorized_result = vectorized.run("TEST.IS", df, verbose=False)
    with settings.override(BACKTEST_FORCE_ITERATIVE=True):
        iterative = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
        assert iterative._use_vectorized_path() is False
        iterative_result = iterative.run("TEST.IS", df, verbose=False)
    assert vectorized_result is not None
    assert iterative_result is not None
    assert vectorized_result.total_trades == iterative_result.total_trades
    assert vectorized_result.final_capital == iterative_result.final_capital
    assert abs(vectorized_result.total_return_pct - iterative_result.total_return_pct) <= 0.01
