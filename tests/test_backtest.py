"""Backtest execution timing tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.backtest import Backtester  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class ScriptedBacktester(Backtester):
    def __init__(self, scripted_signals: dict[int, dict[str, float | bool]]):
        super().__init__(
            initial_capital=1000,
            commission_buy_pct=0.0,
            commission_sell_pct=0.0,
            slippage_pct=0.0,
            indicators=IdentityIndicators(),
        )
        self.scripted_signals = scripted_signals

    def _build_signal_context(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
        return self.scripted_signals.get(
            len(history),
            {
                "enter": False,
                "exit": False,
                "score": 0.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
            },
        )


def build_price_frame() -> pd.DataFrame:
    dates = pd.date_range(datetime(2024, 1, 1), periods=55, freq="D")
    rows = []
    for i, date in enumerate(dates):
        base = 10 + i * 0.1
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 0.5,
                "low": base - 0.5,
                "close": base + 0.1,
                "volume": 1000,
                "atr": 0.0,
                "rsi": 50.0,
                "sma_20": base,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def test_backtester_enters_on_next_bar_open():
    df = build_price_frame()
    df.iloc[1, df.columns.get_loc("open")] = 11.25

    backtester = ScriptedBacktester(
        {
            1: {
                "enter": True,
                "exit": False,
                "score": 25.0,
                "stop_loss": 9.5,
                "target_price": 20.0,
            }
        }
    )

    with settings.override(
        SLIPPAGE_PCT=0.0,
        SLIPPAGE_PENALTY_RATIO=0.0,
        SLIPPAGE_MAX_CAP=0.02,
    ):
        result = backtester.run("TEST.IS", df, verbose=False)

    assert result is not None
    assert result.trades
    assert result.trades[0].entry_date == df.index[1].to_pydatetime()
    assert result.trades[0].entry_price == 11.25


def test_intrabar_simulation_uses_price_path_heuristic_for_same_bar_hits():
    df = build_price_frame()
    df.iloc[1, df.columns.get_loc("open")] = 10.0
    df.iloc[1, df.columns.get_loc("high")] = 12.0
    df.iloc[1, df.columns.get_loc("low")] = 8.0
    df.iloc[1, df.columns.get_loc("close")] = 11.0

    backtester = ScriptedBacktester(
        {
            1: {
                "enter": True,
                "exit": False,
                "score": 30.0,
                "stop_loss": 9.0,
                "target_price": 11.5,
            }
        }
    )

    with settings.override(
        SLIPPAGE_PCT=0.0,
        SLIPPAGE_PENALTY_RATIO=0.0,
        SLIPPAGE_MAX_CAP=0.02,
    ):
        result = backtester.run("TEST.IS", df, verbose=False)

    assert result is not None
    assert result.trades
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == 9.0


def test_dynamic_slippage_uses_atr_on_entry_and_exit():
    df = build_price_frame()
    df.iloc[1, df.columns.get_loc("open")] = 10.0
    df.iloc[1, df.columns.get_loc("close")] = 10.2
    df.iloc[1, df.columns.get_loc("atr")] = 1.0
    df.iloc[-1, df.columns.get_loc("close")] = 15.0
    df.iloc[-1, df.columns.get_loc("atr")] = 1.5

    backtester = ScriptedBacktester(
        {
            1: {
                "enter": True,
                "exit": False,
                "score": 25.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
            }
        }
    )
    with settings.override(
        SLIPPAGE_PCT=0.001,
        SLIPPAGE_PENALTY_RATIO=0.15,
        SLIPPAGE_MAX_CAP=0.02,
    ):
        result = backtester.run("TEST.IS", df, verbose=False)

    assert result is not None
    assert result.trades
    trade = result.trades[0]
    assert trade.entry_price == 10.16
    assert trade.exit_price == 14.76
