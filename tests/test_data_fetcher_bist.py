"""Tests for BISTDataFetcher class, focusing on get_current_price fallback behavior."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd
import pytest

from data_fetcher import BISTDataFetcher, _rate_limiter


@dataclass
class MockScrapeResult:
    success: bool
    price: float | None = None
    change_percent: float | None = None
    source: str = "borsaistanbul.com"
    detail: str = ""

    def to_payload(self):
        if not self.success or self.price is None:
            return None
        return {
            "price": self.price,
            "change_percent": self.change_percent if self.change_percent is not None else 0.0,
            "source": self.source,
        }


def test_get_current_price_realtime_success():
    """Test get_current_price when realtime scraping succeeds."""
    # Create a fetcher with a dummy watchlist
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"])
    
    # Mock the scrape_bist_quote function to return a successful result
    mock_scrape_result = MockScrapeResult(success=True, price=123.45, change_percent=2.5)
    
    with patch("data_fetcher.scrape_bist_quote", return_value=mock_scrape_result) as mock_scrape:
        # Also mock settings to enable realtime scraping
        with patch("data_fetcher.settings") as mock_settings:
            mock_settings.ENABLE_REALTIME_SCRAPING = True
            
            price = fetcher.get_current_price("THYAO.IS")
            
            assert price == 123.45
            mock_scrape.assert_called_once_with("THYAO.IS", _rate_limiter)


def test_get_current_price_realtime_failure_yahoo_fallback():
    """Test get_current_price when realtime scraping fails and Yahoo Finance fallback succeeds."""
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"])
    
    # Mock scrape_bist_quote to return a failed result
    mock_scrape_result = MockScrapeResult(success=False, detail="some error")
    
    # Mock fetch_single to return a dataframe with a close price
    mock_df = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100, 101, 102],
        "volume": [1000, 1100, 1200]
    }, index=pd.date_range(start="2025-01-01", periods=3))
    
    with patch("data_fetcher.scrape_bist_quote", return_value=mock_scrape_result):
        with patch("data_fetcher.settings") as mock_settings:
            mock_settings.ENABLE_REALTIME_SCRAPING = True
            
            with patch.object(fetcher, "fetch_single", return_value=mock_df) as mock_fetch:
                price = fetcher.get_current_price("THYAO.IS")
                
                # Should have called fetch_single with period="5d", interval="1d"
                mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
                assert price == 102.0  # Last close price


def test_get_current_price_both_fail():
    """Test get_current_price when both realtime scraping and Yahoo fallback fail."""
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"])
    
    # Mock scrape_bist_quote to return a failed result
    mock_scrape_result = MockScrapeResult(success=False, detail="some error")
    
    # Mock fetch_single to return None (simulating failure)
    with patch("data_fetcher.scrape_bist_quote", return_value=mock_scrape_result):
        with patch("data_fetcher.settings") as mock_settings:
            mock_settings.ENABLE_REALTIME_SCRAPING = True
            
            with patch.object(fetcher, "fetch_single", return_value=None) as mock_fetch:
                price = fetcher.get_current_price("THYAO.IS")
                
                mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
                assert price is None


def test_get_current_price_realtime_disabled():
    """Test get_current_price when realtime scraping is disabled in settings."""
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"])
    
    # Mock fetch_single to return a dataframe
    mock_df = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100, 101, 102],
        "volume": [1000, 1100, 1200]
    }, index=pd.date_range(start="2025-01-01", periods=3))
    
    with patch("data_fetcher.settings") as mock_settings:
        mock_settings.ENABLE_REALTIME_SCRAPING = False
        
        with patch.object(fetcher, "fetch_single", return_value=mock_df) as mock_fetch:
            price = fetcher.get_current_price("THYAO.IS")
            
            # Should not call scrape_bist_quote at all
            # Note: We don't have a direct way to assert scrape_bist_quote wasn't called without tracking it,
            # but we can check that fetch_single was called.
            mock_fetch.assert_called_once_with("THYAO.IS", period="5d", interval="1d")
            assert price == 102.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
