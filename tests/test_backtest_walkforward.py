"""Walk-forward validation tests."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from bist_bot.backtest import BacktestResult, BacktestTrade, WalkForwardValidator
from bist_bot.strategy.params import StrategyParams


def build_two_year_frame() -> pd.DataFrame:
    dates = pd.date_range(datetime(2023, 1, 1), datetime(2024, 12, 31), freq="D")
    values = []
    for idx, date in enumerate(dates):
        base = 100 + (idx * 0.2)
        values.append(
            {
                "date": date,
                "open": base,
                "high": base + 1.0,
                "low": base - 1.0,
                "close": base + 0.4,
                "volume": 10_000,
            }
        )
    return pd.DataFrame(values).set_index("date")


class DummyOptimizer:
    def __init__(self, ticker: str, train_df: pd.DataFrame, initial_capital: float) -> None:
        self.ticker = ticker
        self.train_df = train_df
        self.initial_capital = initial_capital

    def random_search(self, param_grid: dict[str, list[float]], n_iter: int = 20):
        _ = n_iter
        return StrategyParams(buy_threshold=param_grid["buy_threshold"][0]), None


class DummyBacktester:
    def __init__(self, initial_capital: float, params: StrategyParams) -> None:
        self.initial_capital = initial_capital
        self.params = params

    def run(self, ticker: str, df: pd.DataFrame, verbose: bool = False) -> BacktestResult:
        _ = verbose
        entry_date = df.index[0].to_pydatetime()
        exit_date = df.index[-1].to_pydatetime()
        trade = BacktestTrade(
            entry_date=entry_date,
            exit_date=exit_date,
            ticker=ticker,
            entry_price=100.0,
            exit_price=103.0,
            signal_score=self.params.buy_threshold,
            profit_pct=3.0,
            profit_tl=30.0,
            holding_days=max((exit_date - entry_date).days, 1),
            gross_profit_tl=35.0,
            total_cost_tl=5.0,
            commission_tl=2.0,
            bsmv_tl=1.0,
            exchange_fee_tl=1.0,
            slippage_tl=1.0,
        )
        return BacktestResult(
            ticker=ticker,
            period="synthetic",
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital * 1.03,
            total_return_pct=3.0,
            total_trades=1,
            winning_trades=1,
            losing_trades=0,
            win_rate=100.0,
            avg_profit_pct=3.0,
            avg_loss_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=1.2,
            sortino_ratio=1.5,
            cagr=5.0,
            profit_factor=2.0,
            avg_trade_pct=3.0,
            trades=[trade],
        )


def test_walk_forward_generates_expected_windows_and_metrics() -> None:
    validator = WalkForwardValidator(
        train_window=12,
        test_window=3,
        step=3,
        mode="rolling",
        optimizer_factory=DummyOptimizer,
        backtester_factory=DummyBacktester,
    )

    result = validator.run("TEST.IS", build_two_year_frame(), initial_capital=10_000)

    assert result is not None
    assert len(result.windows) == 3
    assert result.combined_metrics["sharpe"] >= 0
    assert result.combined_metrics["sortino"] >= 0
    assert result.combined_metrics["max_drawdown"] <= 0
    assert result.combined_metrics["cagr"] >= 0
    assert result.combined_metrics["win_rate"] >= 0
    assert result.combined_metrics["profit_factor"] >= 0
    assert result.combined_metrics["avg_trade"] > 0
