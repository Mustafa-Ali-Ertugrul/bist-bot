from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from bist_bot import backtest_compare
from bist_bot.config.settings import settings


def build_frame() -> pd.DataFrame:
    dates = pd.date_range(datetime(2024, 1, 1), periods=60, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0] * 60,
            "high": [101.0] * 60,
            "low": [99.0] * 60,
            "close": [100.5] * 60,
            "volume": [1000] * 60,
        },
        index=dates,
    )


@dataclass
class DummyResult:
    total_return_pct: float
    total_trades: int
    win_rate: float
    sharpe_ratio: float
    max_drawdown_pct: float


def test_run_slippage_sweep_respects_penalty_overrides(monkeypatch) -> None:
    seen_penalties: list[float] = []

    class DummyStrategyEngine:
        pass

    class DummyStrategyBacktester:
        def __init__(self, engine=None):
            _ = engine

        def run(self, ticker: str, df: pd.DataFrame, verbose: bool = False):
            _ = ticker, df, verbose
            seen_penalties.append(settings.SLIPPAGE_PENALTY_RATIO)
            return DummyResult(
                total_return_pct=10.0 - settings.SLIPPAGE_PENALTY_RATIO,
                total_trades=3,
                win_rate=66.0,
                sharpe_ratio=1.2,
                max_drawdown_pct=-4.0,
            )

    monkeypatch.setattr(backtest_compare, "StrategyEngine", DummyStrategyEngine)
    monkeypatch.setattr(backtest_compare, "StrategyBacktester", DummyStrategyBacktester)

    sweep = backtest_compare.run_slippage_sweep(
        "TEST.IS",
        build_frame(),
        penalties=[0.0, 0.15, 0.5],
    )

    assert seen_penalties == [0.0, 0.15, 0.5]
    assert list(sweep["Penalty (ATR Multiplier)"]) == [0.0, 0.15, 0.5]
    assert settings.SLIPPAGE_PENALTY_RATIO != 0.5
