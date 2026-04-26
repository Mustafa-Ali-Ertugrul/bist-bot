"""Abstract base class and plugin interfaces for trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from bist_bot.strategy.signal_models import Signal


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    A strategy receives verified MarketData (as a Pandas DataFrame) and
    returns a Signal if the market conditions align with its logic, or None otherwise.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the strategy."""
        pass

    @abstractmethod
    def analyze(self, ticker: str, data: pd.DataFrame | dict[str, pd.DataFrame]) -> Signal | None:
        """Run the technical and logical analysis.

        Args:
            ticker: The symbol being analyzed.
            data: Standardized technical OHLCV data.

        Returns:
            Signal object if a trade setup is valid, else None.
        """
        pass
