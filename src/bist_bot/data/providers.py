"""Provider adapters for market data and quote acquisition."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from bist_bot.data import quotes as quote_helpers
from bist_bot.data.scraper import scrape_bist_quote


class RateLimiterProtocol(Protocol):
    def wait_if_needed(self, domain: str) -> None: ...


class MarketDataProvider(Protocol):
    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None: ...
    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]: ...
    def fetch_quote(self, ticker: str) -> float | None: ...
    def fetch_universe(self, force_refresh: bool = False) -> list[str]: ...


class QuoteProvider(Protocol):
    def fetch_quote(self, ticker: str) -> float | None: ...


class YFinanceProvider:
    def __init__(self, rate_limiter: RateLimiterProtocol) -> None:
        self.rate_limiter = rate_limiter

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        import yfinance as yf

        self.rate_limiter.wait_if_needed("yahoo.finance")
        stock = yf.Ticker(ticker)
        return stock.history(period=period, interval=interval)

    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]:
        import yfinance as yf

        if not tickers:
            return {}

        self.rate_limiter.wait_if_needed("yahoo.finance")
        raw_data = yf.download(
            tickers=" ".join(tickers),
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
        if raw_data is None or raw_data.empty:
            return {}

        results: dict[str, pd.DataFrame | None] = {}
        for ticker in tickers:
            try:
                if isinstance(raw_data.columns, pd.MultiIndex):
                    results[ticker] = raw_data[ticker].copy()
                else:
                    results[ticker] = raw_data.copy()
            except KeyError:
                results[ticker] = None
        return results

    def fetch_quote(self, ticker: str) -> float | None:
        _ = ticker
        return None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        return quote_helpers.get_bist100_tickers(self.rate_limiter, force_refresh=force_refresh)


class BorsaIstanbulQuoteProvider:
    def __init__(self, rate_limiter: RateLimiterProtocol) -> None:
        self.rate_limiter = rate_limiter

    def fetch_quote(self, ticker: str) -> float | None:
        result = scrape_bist_quote(ticker, self.rate_limiter)
        if result.success and result.price is not None:
            return float(result.price)
        return None


class OfficialProviderStub:
    """Placeholder adapter for future paid/official data sources."""

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        _ = ticker, period, interval
        return None

    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]:
        _ = period, interval
        return {ticker: None for ticker in tickers}

    def fetch_quote(self, ticker: str) -> float | None:
        _ = ticker
        return None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        _ = force_refresh
        return []
