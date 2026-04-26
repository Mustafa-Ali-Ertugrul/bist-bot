from __future__ import annotations

import pandas as pd

from bist_bot import strategy as strategy_module
from bist_bot.contracts import StrategyEngineProtocol
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.signal_models import SignalType

from .engine import Backtester
from .models import BacktestResult


class StrategyBacktester:
    def __init__(
        self,
        initial_capital: float | None = None,
        engine: StrategyEngineProtocol | None = None,
        backtester: Backtester | None = None,
    ) -> None:
        self.engine = engine or strategy_module.StrategyEngine()
        self.backtester = backtester or Backtester(
            initial_capital=initial_capital,
            indicators=TechnicalIndicators(),
        )
        self._enriched_cache: pd.DataFrame | None = None

    @staticmethod
    def _empty_signal_context() -> dict[str, float | bool]:
        return {
            "enter": False,
            "exit": False,
            "score": 0.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        }

    def run(self, ticker: str, df: pd.DataFrame, verbose: bool = False) -> BacktestResult | None:
        self._enriched_cache = TechnicalIndicators().add_all(df.copy())

        def signal_builder(ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
            idx = len(history) - 1
            if self._enriched_cache is None or idx < 0 or idx >= len(self._enriched_cache):
                return self._empty_signal_context()

            enriched_slice = self._enriched_cache.iloc[: idx + 1]
            signal = self.engine.analyze(ticker, enriched_slice, enforce_sector_limit=False)
            if signal is None:
                return self._empty_signal_context()
            return {
                "enter": signal.signal_type in {SignalType.STRONG_BUY, SignalType.BUY},
                "exit": signal.signal_type in {SignalType.SELL, SignalType.STRONG_SELL},
                "score": signal.score,
                "stop_loss": signal.stop_loss,
                "target_price": signal.target_price,
            }

        self.backtester.signal_builder = signal_builder
        try:
            return self.backtester.run(ticker, self._enriched_cache, verbose=verbose)
        finally:
            self.backtester.signal_builder = None
            self._enriched_cache = None
