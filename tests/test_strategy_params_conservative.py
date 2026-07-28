"""Conservative StrategyParams profile and walk-forward wiring tests."""

from __future__ import annotations

from typing import Any

import pandas as pd

from bist_bot.backtest import Backtester
from bist_bot.backtest.models import CostModel
from bist_bot.strategy.params import StrategyParams
from bist_bot.validation import WalkForwardValidator


def test_conservative_profile_values() -> None:
    p = StrategyParams.conservative()
    default = StrategyParams()

    assert p.buy_threshold == 25.0
    assert p.sell_threshold == -25.0
    assert p.sideways_score_multiplier == 0.4
    assert p.adx_threshold == 20.0

    # ~30% lower mean-reversion weights
    assert p.score_rsi_extreme == 12.6
    assert p.score_rsi_normal == 9.8
    assert p.score_rsi_weak_low == 4.9
    assert p.score_rsi_weak_high == 2.8
    assert p.score_stoch_cross == 5.6
    assert p.score_stoch_extreme == 4.2
    assert p.score_stoch_trend == 2.1

    assert p.buy_threshold > default.buy_threshold
    assert abs(p.sell_threshold) > abs(default.sell_threshold)
    assert p.sideways_score_multiplier < default.sideways_score_multiplier
    assert p.score_rsi_extreme < default.score_rsi_extreme
    assert p.score_stoch_cross < default.score_stoch_cross


def test_backtester_uses_strategy_params_thresholds() -> None:
    params = StrategyParams.conservative()
    bt = Backtester(initial_capital=10_000, strategy_params=params)
    assert bt.strategy_params is params
    assert bt.buy_threshold == 25.0
    assert bt.sell_threshold == -25.0


def test_walk_forward_passes_strategy_params_to_factory() -> None:
    captured: dict[str, Any] = {}
    params = StrategyParams.conservative()

    def factory(
        *,
        initial_capital: float,
        cost_model: CostModel | None,
        commission_buy_pct: float | None,
        commission_sell_pct: float | None,
        slippage_pct: float | None,
        strategy_params: Any | None = None,
    ) -> Any:
        captured["strategy_params"] = strategy_params
        captured["initial_capital"] = initial_capital

        class Stub:
            def run(self, ticker: str, df: pd.DataFrame, verbose: bool = False):
                from bist_bot.backtest.models import BacktestResult

                _ = ticker, df, verbose
                return BacktestResult(
                    ticker="X",
                    period="p",
                    initial_capital=initial_capital,
                    final_capital=initial_capital,
                    total_return_pct=1.0,
                    total_trades=0,
                    winning_trades=0,
                    losing_trades=0,
                    win_rate=0.0,
                    avg_profit_pct=0.0,
                    avg_loss_pct=0.0,
                    max_drawdown_pct=0.0,
                    sharpe_ratio=0.0,
                    trades=[],
                )

        return Stub()

    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        },
        index=dates,
    )
    wf = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=100,
        strategy_params=params,
        backtester_factory=factory,
    )
    result = wf.run("TEST.IS", df)
    assert result is not None
    assert captured["strategy_params"] is params
    assert captured["strategy_params"].buy_threshold == 25.0
