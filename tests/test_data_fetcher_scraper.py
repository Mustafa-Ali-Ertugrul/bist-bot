"""Tests for BIST data scraper functionality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generator
import pytest
import requests

from data_fetcher_scraper import (
    _parse_number,
    _extract_quote_from_text,
    _extract_quote_from_html,
    ScrapeQuoteResult,
    scrape_bist_quote,
)


@dataclass
class MockResponse:
    """Mock HTTP response for testing."""
    text: str
    status_code: int = 200

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


@dataclass
class MockRateLimiter:
    """Mock rate limiter that records calls."""
    waited_domains: list[str]

    def wait_if_needed(self, domain: str) -> None:
        self.waited_domains.append(domain)


def test_parse_number_various_formats():
    """Number parsing handles Turkish formatting and symbols."""
    assert _parse_number("1.234,56") == 1234.56
    assert _parse_number("100,00") == 100.0
    assert _parse_number("0,01") == 0.01
    assert _parse_number("%12,50") == 12.5
    assert _parse_number("-5,20") == -5.2
    assert _parse_number(" +3,5% ") == 3.5
    assert _parse_number("abc") is None
    assert _parse_number("") is None


def test_extract_quote_from_text_finds_price_and_change():
    """Quote extraction works with Turkish labels."""
    blob = "Hisse Seneti: THYAO Son Değer 123,45 Yüksek 125,00 Değişim% +2,5"
    price, change = _extract_quote_from_text(blob)
    assert price == 123.45
    assert change == 2.5
    
    # Test negative percentage
    blob2 = "LastPrice 50,00 changePercent -1,25"
    price2, change2 = _extract_quote_from_text(blob2)
    assert price2 == 50.0
    assert change2 == -1.25


def test_extract_quote_from_text_returns_none_when_not_found():
    """Quote extraction returns None when patterns not found."""
    blob = "Bu bir metin fiyat bilgisi yok"
    price, change = _extract_quote_from_text(blob)
    assert price is None
    assert change is None


def test_extract_quote_from_html_success():
    """HTML parsing extracts quote when present."""
    html = """
    <html>
    <body>
        <div class="quote">Hisse Seneti: THYAO Son Değer 123,45</div>
        <div class="change">Değişim% +2,5</div>
    </body>
    </html>
    """
    result = _extract_quote_from_html(html)
    assert result.success is True
    assert result.price == 123.45
    assert result.change_percent == 2.5
    assert result.source == "borsaistanbul.com"


def test_extract_quote_from_html_empty():
    """HTML parsing handles empty input."""
    result = _extract_quote_from_html("")
    assert result.success is False
    assert result.detail == "bos-govde"

    result = _extract_quote_from_html("   ")
    assert result.success is False
    assert result.detail == "bos-govde"


def test_extract_quote_from_html_no_price():
    """HTML parsing handles missing price data."""
    html = """
    <html>
    <body>
        <div>Bu bir metin fiyat yok</div>
    </body>
    </html>
    """
    result = _extract_quote_from_html(html)
    assert result.success is False
    assert result.detail == "fiyat-alani-bulunamadi"


def test_scrape_bist_quote_success(monkeypatch):
    """Scraping succeeds when HTML contains price data."""
    # Setup mocks
    mock_html = """
    <html>
    <body>
        <div>Hisse Seneti: THYAO Son Değer 123,45</div>
        <div>Değişim% +2,5</div>
    </body>
    </html>
    """
    mock_response = MockResponse(text=mock_html)
    
    waited_domains = []
    mock_limiter = MockRateLimiter(waited_domains)
    
    def mock_get(url, timeout, headers):
        assert timeout == 10
        assert headers == {"User-Agent": "Mozilla/5.0"}
        return mock_response
    
    monkeypatch.setattr("data_fetcher_scraper.requests.get", mock_get)
    
    # Execute
    result = scrape_bist_quote("THYAO.IS", mock_limiter)
    
    # Verify
    assert result.success is True
    assert result.price == 123.45
    assert result.change_percent == 2.5
    assert "borsaistanbul.com.tr" in waited_domains


def test_scrape_bist_quote_timeout_retry(monkeypatch):
    """Scraping retries on timeout and succeeds on second attempt."""
    call_count = 0
    
    def mock_get(url, timeout, headers):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.exceptions.Timeout()
        # Second attempt succeeds
        mock_html = """
        <html>
        <body>
            <div>Hisse Seneti: THYAO Son Değer 100,00</div>
        </body>
        </html>
        """
        return MockResponse(text=mock_html)
    
    waited_domains = []
    mock_limiter = MockRateLimiter(waited_domains)
    
    monkeypatch.setattr("data_fetcher_scraper.requests.get", mock_get)
    
    result = scrape_bist_quote("THYAO.IS", mock_limiter)
    
    assert result.success is True
    assert result.price == 100.0
    assert len(waited_domains) == 2  # Called twice


def test_scrape_bist_quote_all_failures(monkeypatch):
    """Scraping returns failure when all attempts fail."""
    waited_domains = []
    mock_limiter = MockRateLimiter(waited_domains)
    
    def mock_get(url, timeout, headers):
        raise requests.exceptions.RequestException("network error")
    
    monkeypatch.setattr("data_fetcher_scraper.requests.get", mock_get)
    
    result = scrape_bist_quote("THYAO.IS", mock_limiter)
    
    assert result.success is False
    assert "ag-hatasi:" in result.detail or "timeout:" in result.detail
    assert len(waited_domains) == 2  # Two URLs attempted