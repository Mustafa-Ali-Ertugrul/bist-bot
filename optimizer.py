"""Strategy Parameter Optimizer for BIST-Bot."""

import itertools
import random
import logging
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

from strategy_params import StrategyParams
from strategy import StrategyEngine
from backtest import StrategyBacktester, BacktestResult
from config import settings

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    def __init__(
        self,
        ticker: str,
        df: pd.DataFrame,
        initial_capital: float = None,
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
        self.best_params: Optional[StrategyParams] = None
        self.best_result: Optional[BacktestResult] = None
        self.best_score: float = -float("inf")
        self.optimization_history: List[Dict[str, Any]] = []

    def _fitness_function(self, result: BacktestResult) -> float:
        """Score a backtest result for optimizer ranking."""
        if result.total_return_pct <= 0 or result.total_trades == 0:
            return result.total_return_pct

        sharpe_multiplier = max(result.sharpe_ratio, 0.1)
        win_rate_multiplier = max(result.win_rate / 100, 0.1)
        return result.total_return_pct * sharpe_multiplier * win_rate_multiplier

    def _evaluate_combination(self, param_dict: Dict[str, Any]) -> None:
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
                    f"🌟 Yeni En İyi Bulundu! Skor: {score:.2f} | "
                    f"Getiri: %{result.total_return_pct:.2f} | İşlem: {result.total_trades}"
                )

    def grid_search(
        self,
        param_grid: Dict[str, List[Any]],
    ) -> Tuple[Optional[StrategyParams], Optional[BacktestResult]]:
        """Try every parameter combination in the provided grid."""
        keys = param_grid.keys()
        combinations = list(itertools.product(*(param_grid[key] for key in keys)))
        total_combos = len(combinations)

        logger.info(f"🔍 Grid Search Başlıyor... Toplam {total_combos} kombinasyon test edilecek.")

        for i, combo in enumerate(combinations):
            if i % 10 == 0:
                logger.info(f"⏳ İlerleme: {i}/{total_combos} ({(i / total_combos) * 100:.1f}%)")

            param_dict = dict(zip(keys, combo))
            self._evaluate_combination(param_dict)

        logger.info("✅ Grid Search Tamamlandı!")
        return self.best_params, self.best_result

    def random_search(
        self,
        param_grid: Dict[str, List[Any]],
        n_iter: int = 50,
    ) -> Tuple[Optional[StrategyParams], Optional[BacktestResult]]:
        """Try random parameter combinations from the provided search space."""
        logger.info(f"🎲 Random Search Başlıyor... Rastgele {n_iter} kombinasyon test edilecek.")

        for i in range(n_iter):
            if i % 10 == 0:
                logger.info(f"⏳ İlerleme: {i}/{n_iter} ({(i / n_iter) * 100:.1f}%)")

            param_dict = {key: random.choice(values) for key, values in param_grid.items()}
            self._evaluate_combination(param_dict)

        logger.info("✅ Random Search Tamamlandı!")
        return self.best_params, self.best_result

    def get_top_n_results(self, n: int = 5) -> pd.DataFrame:
        """Return top optimization results as a dataframe."""
        if not self.optimization_history:
            return pd.DataFrame()

        df_history = pd.DataFrame(self.optimization_history)
        df_history = df_history.sort_values(by="score", ascending=False).head(n)
        return df_history


if __name__ == "__main__":
    from data_fetcher import BISTDataFetcher

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    fetcher = BISTDataFetcher()
    ticker = "THYAO.IS"

    print(f"📊 {ticker} verisi indiriliyor...")
    df = fetcher.fetch_single(ticker, period="1y")

    if df is not None:
        optimizer = StrategyOptimizer(ticker=ticker, df=df)

        search_space = {
            "buy_threshold": [8.0, 10.0, 15.0],
            "sell_threshold": [-8.0, -10.0, -15.0],
            "rsi_oversold": [25.0, 30.0, 35.0],
            "score_macd_cross": [8.0, 12.0, 15.0],
            "score_sma_golden_cross": [10.0, 12.0, 18.0],
        }

        best_params, best_result = optimizer.random_search(search_space, n_iter=20)

        print("\n" + "=" * 50)
        print("🏆 OPTİMİZASYON SONUCU")
        print("=" * 50)
        if best_result and best_params:
            print(best_result)
            print("\n⚙️ EN İYİ PARAMETRELER:")
            print(f"  Buy Threshold: {best_params.buy_threshold}")
            print(f"  Sell Threshold: {best_params.sell_threshold}")
            print(f"  RSI Oversold: {best_params.rsi_oversold}")
            print(f"  MACD Skoru: {best_params.score_macd_cross}")
            print(f"  SMA Skoru: {best_params.score_sma_golden_cross}")

            print("\n📋 İlk 5 Alternatif Sonuç:")
            top_5 = optimizer.get_top_n_results(5)
            print(top_5[["return_pct", "win_rate", "sharpe", "trades", "score"]].to_string(index=False))
        else:
            print("Uygun bir sonuç bulunamadı.")
