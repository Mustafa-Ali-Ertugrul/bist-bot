"""Tests for BISTDataFetcher class, focusing on get_current_price fallback behavior."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from bist_bot.data.fetcher import BISTDataFetcher

def test_get_current_price_realtime_success():
    """Test get_current_price when realtime scraping succeeds."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=123.45)
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider)

    with patch("bist_bot.data.fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = True

        price = fetcher.get_current_price("THYAO.IS")

    assert price == 123.45
    assert quote_provider.calls == ["THYAO.IS"]


def test_get_current_price_realtime_failure_yahoo_fallback():
    """Test get_current_price when realtime scraping fails and Yahoo Finance fallback succeeds."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=None)
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider)

    mock_df = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100, 101, 102],
        "volume": [1000, 1100, 1200]
    }, index=pd.date_range(start="2025-01-01", periods=3))

    with patch("bist_bot.data.fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = True

        with patch.object(fetcher, "fetch_single", return_value=mock_df) as mock_fetch:
            price = fetcher.get_current_price("THYAO.IS")

            mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
            assert price == 102.0


def test_get_current_price_both_fail():
    """Test get_current_price when both realtime scraping and Yahoo fallback fail."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=None)
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider)

    with patch("bist_bot.data.fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = True

        with patch.object(fetcher, "fetch_single", return_value=None) as mock_fetch:
            price = fetcher.get_current_price("THYAO.IS")

            mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
            assert price is None


def test_get_current_price_realtime_disabled():
    """Test get_current_price when realtime scraping is disabled in settings."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=123.45)
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider)

    mock_df = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100, 101, 102],
        "volume": [1000, 1100, 1200]
    }, index=pd.date_range(start="2025-01-01", periods=3))
    with patch("bist_bot.data.fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = False

        with patch.object(fetcher, "fetch_single", return_value=mock_df) as mock_fetch:
            price = fetcher.get_current_price("THYAO.IS")

            mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
            assert price == 102.0
            assert quote_provider.calls == []


class MockProvider:
    def fetch_history(self, ticker: str, period: str, interval: str):
        _ = ticker, period, interval
        return None

    def fetch_batch(self, tickers: list[str], period: str, interval: str):
        _ = tickers, period, interval
        return {}

    def fetch_quote(self, ticker: str):
        _ = ticker
        return None

    def fetch_universe(self, force_refresh: bool = False):
        _ = force_refresh
        return ["THYAO.IS"]


class MockQuoteProvider:
    def __init__(self, price: float | None):
        self.price = price
        self.calls: list[str] = []

    def fetch_quote(self, ticker: str):
        self.calls.append(ticker)
        return self.price


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
