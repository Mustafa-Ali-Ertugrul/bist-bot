from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, cast

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot import strategy as strategy_module

from .models import (
    BacktestTrade,
    WalkForwardResult,
    WalkForwardWindowResult,
    WindowMode,
    _summarize_trades_and_equity,
    _to_datetime,
)
from .strategy import StrategyBacktester

logger = get_logger(__name__, component="backtest")


class WalkForwardValidator:
    def __init__(
        self,
        train_window: int = 12,
        test_window: int = 3,
        step: int = 3,
        mode: str = WindowMode.ROLLING.value,
        optimizer_iterations: int = 20,
        param_grid: Optional[dict[str, list[Any]]] = None,
        optimizer_factory: Any | None = None,
        backtester_factory: Any | None = None,
    ) -> None:
        self.train_window = train_window
        self.test_window = test_window
        self.step = step
        self.mode = WindowMode(mode)
        self.optimizer_iterations = optimizer_iterations
        self.param_grid = param_grid or {
            "buy_threshold": [12.0, 15.0, 20.0],
            "sell_threshold": [-12.0, -20.0, -28.0],
            "score_macd_cross": [8.0, 12.0, 15.0],
            "score_sma_golden_cross": [10.0, 12.0, 15.0],
        }
        self.optimizer_factory = optimizer_factory
        self.backtester_factory = backtester_factory

    def _build_windows(
        self, df: pd.DataFrame
    ) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        windows: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        if df.empty:
            return windows

        index = pd.DatetimeIndex(df.index)
        start_date = _to_datetime(index.min())
        end_date = _to_datetime(index.max())
        current_train_start = pd.Timestamp(start_date)
        current_train_months = self.train_window

        while True:
            train_end = current_train_start + pd.DateOffset(months=current_train_months)
            test_end = train_end + pd.DateOffset(months=self.test_window)
            if test_end > end_date:
                break

            train_df = df.loc[
                (df.index >= current_train_start) & (df.index < train_end)
            ]
            test_df = df.loc[(df.index >= train_end) & (df.index < test_end)]
            if not train_df.empty and not test_df.empty:
                windows.append((train_df, test_df))

            if self.mode is WindowMode.ROLLING:
                current_train_start = current_train_start + pd.DateOffset(
                    months=self.step
                )
            else:
                current_train_start = pd.Timestamp(start_date)
                current_train_months += self.step

        return windows

    def _optimizer(
        self, ticker: str, train_df: pd.DataFrame, initial_capital: float
    ) -> Any:
        if self.optimizer_factory is not None:
            return self.optimizer_factory(ticker, train_df, initial_capital)

        from bist_bot.optimizer import StrategyOptimizer

        return StrategyOptimizer(
            ticker=ticker, df=train_df, initial_capital=initial_capital
        )

    def _backtester(self, initial_capital: float, params: Any) -> StrategyBacktester:
        if self.backtester_factory is not None:
            return cast(
                StrategyBacktester, self.backtester_factory(initial_capital, params)
            )

        engine = strategy_module.StrategyEngine(params=params)
        return StrategyBacktester(initial_capital=initial_capital, engine=engine)

    def run(
        self,
        ticker: str,
        df: pd.DataFrame,
        initial_capital: Optional[float] = None,
        output_path: str | Path | None = None,
        universe_as_of: str | None = None,
    ) -> Optional[WalkForwardResult]:
        if df is None or df.empty:
            return None

        initial = (
            float(initial_capital)
            if initial_capital is not None
            else float(getattr(settings, "INITIAL_CAPITAL", 8500.0))
        )
        df_sorted = df.sort_index()
        windows = self._build_windows(df_sorted)
        if not windows:
            return None

        compounded_capital = initial
        equity_history = [initial]
        combined_trades: list[BacktestTrade] = []
        window_results: list[WalkForwardWindowResult] = []

        for idx, (train_df, test_df) in enumerate(windows, start=1):
            optimizer = self._optimizer(ticker, train_df, initial)
            best_params, _ = optimizer.random_search(
                self.param_grid, n_iter=self.optimizer_iterations
            )
            if best_params is None:
                continue

            backtester = self._backtester(initial, best_params)
            test_result = backtester.run(ticker, test_df, verbose=False)
            if test_result is None:
                continue

            compounded_capital *= 1 + (test_result.total_return_pct / 100)
            equity_history.append(compounded_capital)
            combined_trades.extend(test_result.trades)

            params_dict = getattr(best_params, "__dict__", {})
            window_results.append(
                WalkForwardWindowResult(
                    window_index=idx,
                    train_period=f"{_to_datetime(train_df.index[0]).strftime('%Y-%m-%d')} -> {_to_datetime(train_df.index[-1]).strftime('%Y-%m-%d')}",
                    test_period=f"{_to_datetime(test_df.index[0]).strftime('%Y-%m-%d')} -> {_to_datetime(test_df.index[-1]).strftime('%Y-%m-%d')}",
                    train_rows=len(train_df),
                    test_rows=len(test_df),
                    params={
                        key: value
                        for key, value in params_dict.items()
                        if key in self.param_grid
                    },
                    metrics=test_result.to_dict(),
                )
            )

        if not window_results:
            return None

        combined_summary = _summarize_trades_and_equity(
            ticker=ticker,
            start_date=_to_datetime(df_sorted.index[0]),
            end_date=_to_datetime(df_sorted.index[-1]),
            initial_capital=initial,
            final_capital=compounded_capital,
            trades=combined_trades,
            equity_history=equity_history,
        )
        combined_metrics = {
            "sharpe": combined_summary["sharpe_ratio"],
            "sortino": combined_summary["sortino_ratio"],
            "max_drawdown": combined_summary["max_drawdown_pct"],
            "cagr": combined_summary["cagr"],
            "win_rate": combined_summary["win_rate"],
            "profit_factor": combined_summary["profit_factor"],
            "avg_trade": combined_summary["avg_trade_pct"],
            "total_return_pct": combined_summary["total_return_pct"],
            "final_capital": combined_summary["final_capital"],
            "total_trades": combined_summary["total_trades"],
        }

        result = WalkForwardResult(
            ticker=ticker,
            initial_capital=initial,
            final_capital=round(compounded_capital, 2),
            train_window_months=self.train_window,
            test_window_months=self.test_window,
            step_months=self.step,
            mode=self.mode.value,
            universe_as_of=universe_as_of,
            windows=window_results,
            combined_metrics=combined_metrics,
        )

        if output_path is not None:
            result.to_json(output_path)
        return result

