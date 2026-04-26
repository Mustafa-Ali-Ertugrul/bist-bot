"""Strategy Parameter Optimizer for BIST-Bot."""

import itertools
import random
from typing import Any

import pandas as pd

from bist_bot.app_logging import configure_logging, get_logger
from bist_bot.backtest import BacktestResult, StrategyBacktester
from bist_bot.config.settings import settings
from bist_bot.strategy import StrategyEngine
from bist_bot.strategy.params import StrategyParams

logger = get_logger(__name__, component="optimizer")


class StrategyOptimizer:
    def __init__(
        self,
        ticker: str,
        df: pd.DataFrame,
        initial_capital: float | None = None,
    ):
        """Initialize optimizer state for a single ticker dataset.

        Args:
            ticker: Test edilecek hisse sembolü (örn: "THYAO.IS")
            df: İlgili hissenin geçmiş veri seti
            initial_capital: Başlangıç sermayesi
        """
        self.ticker = ticker
        self.df = df
        self.initial_capital = initial_capital or getattr(settings, "INITIAL_CAPITAL", 8500.0)
        self.best_params: StrategyParams | None = None
        self.best_result: BacktestResult | None = None
        self.best_score: float = -float("inf")
        self.optimization_history: list[dict[str, Any]] = []

    def _fitness_function(self, result: BacktestResult) -> float:
        """Score a backtest result for optimizer ranking."""
        if result.total_return_pct <= 0 or result.total_trades == 0:
            return result.total_return_pct

        sharpe_multiplier = max(result.sharpe_ratio, 0.1)
        win_rate_multiplier = max(result.win_rate / 100, 0.1)
        return result.total_return_pct * sharpe_multiplier * win_rate_multiplier

    def _evaluate_combination(self, param_dict: dict[str, Any]) -> None:
        """Test a single parameter combination and record its score."""
        params = StrategyParams(**param_dict)
        engine = StrategyEngine(params=params)
        backtester = StrategyBacktester(
            initial_capital=self.initial_capital,
            engine=engine,
        )

        result = backtester.run(self.ticker, self.df, verbose=False)

        if result:
            score = self._fitness_function(result)
            self.optimization_history.append(
                {
                    "params": param_dict,
                    "score": score,
                    "return_pct": result.total_return_pct,
                    "sharpe": result.sharpe_ratio,
                    "win_rate": result.win_rate,
                    "trades": result.total_trades,
                }
            )

            if score > self.best_score and result.total_trades > 0:
                self.best_score = score
                self.best_params = params
                self.best_result = result
                logger.info(
                    "optimizer_new_best",
                    ticker=self.ticker,
                    score=round(score, 2),
                    return_pct=round(result.total_return_pct, 2),
                    trade_count=result.total_trades,
                )

    def grid_search(
        self,
        param_grid: dict[str, list[Any]],
    ) -> tuple[StrategyParams | None, BacktestResult | None]:
        """Try every parameter combination in the provided grid."""
        keys = param_grid.keys()
        combinations = list(itertools.product(*(param_grid[key] for key in keys)))
        total_combos = len(combinations)

        logger.info("optimizer_grid_search_started", total_combinations=total_combos)

        for i, combo in enumerate(combinations):
            if i % 10 == 0:
                logger.info(
                    "optimizer_grid_search_progress",
                    completed=i,
                    total=total_combos,
                    progress_pct=round((i / total_combos) * 100, 1),
                )

            param_dict = dict(zip(keys, combo, strict=False))
            self._evaluate_combination(param_dict)

        logger.info("optimizer_grid_search_finished")
        return self.best_params, self.best_result

    def random_search(
        self,
        param_grid: dict[str, list[Any]],
        n_iter: int = 50,
    ) -> tuple[StrategyParams | None, BacktestResult | None]:
        """Try random parameter combinations from the provided search space."""
        logger.info("optimizer_random_search_started", iteration_count=n_iter)

        for i in range(n_iter):
            if i % 10 == 0:
                logger.info(
                    "optimizer_random_search_progress",
                    completed=i,
                    total=n_iter,
                    progress_pct=round((i / n_iter) * 100, 1),
                )

            param_dict = {key: random.choice(values) for key, values in param_grid.items()}
            self._evaluate_combination(param_dict)

        logger.info("optimizer_random_search_finished")
        return self.best_params, self.best_result

    def get_top_n_results(self, n: int = 5) -> pd.DataFrame:
        """Return top optimization results as a dataframe."""
        if not self.optimization_history:
            return pd.DataFrame()

        df_history = pd.DataFrame(self.optimization_history)
        df_history = df_history.sort_values(by="score", ascending=False).head(n)
        return df_history

    def walk_forward_validation(
        self,
        param_grid: dict[str, list[Any]],
        train_window_days: int = 180,
        test_window_days: int = 60,
        n_iter: int = 20,
    ) -> pd.DataFrame:
        """Run rolling walk-forward validation on the current dataset."""
        logger.info(
            "optimizer_walk_forward_started",
            train_window_days=train_window_days,
            test_window_days=test_window_days,
        )

        results = []
        df_sorted = self.df.sort_index()

        if df_sorted.empty or len(df_sorted) < (train_window_days + test_window_days):
            logger.error("optimizer_walk_forward_insufficient_data")
            return pd.DataFrame()

        start_date = df_sorted.index[0]
        end_date = df_sorted.index[-1]

        current_train_start = start_date
        window_idx = 1

        while True:
            current_train_end = current_train_start + pd.Timedelta(days=train_window_days)
            current_test_end = current_train_end + pd.Timedelta(days=test_window_days)

            if current_test_end > end_date:
                break

            train_df = df_sorted.loc[current_train_start:current_train_end]
            test_df = df_sorted.loc[current_train_end:current_test_end]

            train_start_str = str(current_train_start)[:10]
            train_end_str = str(current_train_end)[:10]
            test_end_str = str(current_test_end)[:10]

            logger.info(
                "optimizer_walk_forward_window_started",
                window_index=window_idx,
                train_start=train_start_str,
                train_end=train_end_str,
                test_end=test_end_str,
            )

            train_optimizer = StrategyOptimizer(self.ticker, train_df, self.initial_capital)
            best_params, _ = train_optimizer.random_search(param_grid, n_iter=n_iter)

            if best_params is None:
                logger.warning(
                    "optimizer_walk_forward_window_skipped",
                    window_index=window_idx,
                )
                current_train_start += pd.Timedelta(days=test_window_days)
                window_idx += 1
                continue

            test_engine = StrategyEngine(params=best_params)
            test_backtester = StrategyBacktester(
                initial_capital=self.initial_capital, engine=test_engine
            )
            test_result = test_backtester.run(self.ticker, test_df, verbose=False)

            if test_result:
                results.append(
                    {
                        "Window": window_idx,
                        "OOS_Return_Pct": test_result.total_return_pct,
                        "OOS_Win_Rate": test_result.win_rate,
                        "OOS_Sharpe": test_result.sharpe_ratio,
                        "OOS_Trades": test_result.total_trades,
                        "Params_Used": {
                            k: v for k, v in best_params.__dict__.items() if k in param_grid
                        },
                    }
                )
                logger.info(
                    "optimizer_walk_forward_window_completed",
                    window_index=window_idx,
                    oos_return_pct=round(test_result.total_return_pct, 2),
                    trade_count=test_result.total_trades,
                )
            else:
                logger.info(
                    "optimizer_walk_forward_window_no_trades",
                    window_index=window_idx,
                )

            current_train_start += pd.Timedelta(days=test_window_days)
            window_idx += 1

        logger.info("optimizer_walk_forward_finished", window_count=len(results))
        return pd.DataFrame(results)


if __name__ == "__main__":
    from bist_bot.data.fetcher import BISTDataFetcher

    configure_logging(level="INFO", fmt="%(message)s")

    fetcher = BISTDataFetcher()
    ticker = "THYAO.IS"

    print(f"📊 {ticker} verisi indiriliyor...")
    df = fetcher.fetch_single(ticker, period="1y")

    if df is not None:
        optimizer = StrategyOptimizer(ticker=ticker, df=df)

        search_space = {
            "buy_threshold": [8.0, 10.0, 12.0, 15.0],
            "score_macd_cross": [8.0, 12.0, 15.0],
            "score_sma_golden_cross": [10.0, 12.0, 15.0],
        }

        wf_results = optimizer.walk_forward_validation(
            search_space,
            train_window_days=180,
            test_window_days=60,
            n_iter=15,
        )

        if not wf_results.empty:
            print("\n" + "=" * 60)
            print("🚀 WALK-FORWARD (OUT-OF-SAMPLE) SONUÇLARI")
            print("=" * 60)
            print(wf_results.to_string(index=False))

            mean_return = wf_results["OOS_Return_Pct"].mean()
            print(f"\nOrtalama OOS Getiri (Aylık/Dönemsel): %{mean_return:.2f}")
