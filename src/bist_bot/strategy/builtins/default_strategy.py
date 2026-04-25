"""Default built-in strategy: wraps the existing multi-timeframe StrategyEngine."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from bist_bot.strategy.base import BaseStrategy
from bist_bot.strategy.signal_models import Signal


class DefaultEngineStrategy(BaseStrategy):
    """Wraps the existing ``StrategyEngine`` so it plugs into the new registry.

    This is the reference built-in strategy shipped with BIST Bot. It delegates
    all scoring/signal logic to the proven multi-timeframe engine already in
    ``bist_bot.strategy.engine``, keeping the plugin interface stable.
    """

    def __init__(self, engine: Optional[object] = None) -> None:
        """Initialize with an optional pre-built ``StrategyEngine`` instance.

        If no engine is supplied one is created with default parameters so the
        strategy can be used with zero configuration.

        Args:
            engine: An optional ``StrategyEngine`` instance.
        """
        if engine is None:
            # Lazy import to avoid circular dependency at module level.
            from bist_bot.strategy.engine import StrategyEngine

            engine = StrategyEngine()
        self._engine = engine

    @property
    def name(self) -> str:
        return "DefaultEngineStrategy"

    def analyze(
        self, ticker: str, data: pd.DataFrame | dict[str, pd.DataFrame]
    ) -> Signal | None:
        """Delegate to the underlying ``StrategyEngine.analyze`` method.

        Args:
            ticker: Stock symbol.
            data: Either a single OHLCV DataFrame or a ``{"trend": …, "trigger": …}`` dict.

        Returns:
            Signal or None.
        """
        return self._engine.analyze(ticker, data)  # type: ignore[return-value]
