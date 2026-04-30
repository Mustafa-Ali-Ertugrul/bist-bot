"""Tests for BISTDataFetcher class, focusing on get_current_price fallback behavior."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pandas as pd
import pytest

from bist_bot.data.fetcher import BISTDataFetcher


def test_get_current_price_realtime_success(caplog):
    """Test get_current_price when realtime scraping succeeds."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=123.45)
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider
    )

    with patch("bist_bot.data.fetcher.settings") as mock_settings, caplog.at_level(logging.INFO):
        mock_settings.ENABLE_REALTIME_SCRAPING = True

        price = fetcher.get_current_price("THYAO.IS")

    assert price == 123.45
    assert quote_provider.calls == ["THYAO.IS"]
    assert fetcher.get_last_quote_resolution_meta("THYAO.IS") == {
        "source": "scrape",
        "status": "success",
    }
    assert "quote_resolution_completed" in caplog.text
    assert "quote_source=scrape" in caplog.text


def test_get_current_price_realtime_failure_yahoo_fallback():
    """Test get_current_price when realtime scraping fails and Yahoo Finance fallback succeeds."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=None)
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider
    )

    mock_df = pd.DataFrame(
        {
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100, 101, 102],
            "volume": [1000, 1100, 1200],
        },
        index=pd.date_range(start="2025-01-01", periods=3),
    )

    with patch("bist_bot.data.fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = True

        with patch.object(fetcher, "fetch_single", return_value=mock_df) as mock_fetch:
            with patch.object(
                fetcher,
                "get_last_history_fetch_meta",
                return_value={"source": "single", "status": "success"},
            ):
                price = fetcher.get_current_price("THYAO.IS")

                mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
                assert price == 102.0
                assert fetcher.get_last_quote_resolution_meta("THYAO.IS") == {
                    "source": "history_fallback",
                    "status": "success",
                    "reason": "single",
                }


def test_get_current_price_both_fail(caplog):
    """Test get_current_price when both realtime scraping and Yahoo fallback fail."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=None)
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider
    )

    with patch("bist_bot.data.fetcher.settings") as mock_settings, caplog.at_level(logging.INFO):
        mock_settings.ENABLE_REALTIME_SCRAPING = True

        with patch.object(fetcher, "fetch_single", return_value=None) as mock_fetch:
            with patch.object(
                fetcher,
                "get_last_history_fetch_meta",
                return_value={"source": "batch_fallback", "status": "failed"},
            ):
                price = fetcher.get_current_price("THYAO.IS")

                mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
                assert price is None
                assert fetcher.get_last_quote_resolution_meta("THYAO.IS") == {
                    "source": "failed",
                    "status": "failed",
                    "reason": "batch_fallback",
                }
                assert "quote_resolution_terminal_failed" in caplog.text
                assert "quote_source=failed" in caplog.text


def test_get_current_price_realtime_disabled():
    """Test get_current_price when realtime scraping is disabled in settings."""
    provider = MockProvider()
    quote_provider = MockQuoteProvider(price=123.45)
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"], provider=provider, quote_provider=quote_provider
    )

    mock_df = pd.DataFrame(
        {
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100, 101, 102],
            "volume": [1000, 1100, 1200],
        },
        index=pd.date_range(start="2025-01-01", periods=3),
    )
    with patch("bist_bot.data.fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = False

        with patch.object(fetcher, "fetch_single", return_value=mock_df) as mock_fetch:
            with patch.object(
                fetcher,
                "get_last_history_fetch_meta",
                return_value={"source": "single", "status": "success"},
            ):
                price = fetcher.get_current_price("THYAO.IS")

                mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
                assert price == 102.0
                assert quote_provider.calls == []
                assert fetcher.get_last_quote_resolution_meta("THYAO.IS") == {
                    "source": "history_fallback",
                    "status": "success",
                    "reason": "single",
                }


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
