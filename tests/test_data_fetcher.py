"""Data fetcher helper tests."""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def test_parse_tr_number():
    """Parse Turkish number formatting correctly."""
    from bist_bot.data.fetcher import _parse_tr_number

    assert _parse_tr_number("1.234,56") == pytest.approx(1234.56)
    assert _parse_tr_number("100,00") == pytest.approx(100.0)
    assert _parse_tr_number("0,01") == pytest.approx(0.01)
    assert _parse_tr_number("%12,50") == pytest.approx(12.5)
    assert _parse_tr_number("abc") is None


def test_rate_limiter_initializes_request_store():
    """Rate limiter should start with an empty request registry."""
    from bist_bot.data.fetcher import RateLimiter

    limiter = RateLimiter()

    assert isinstance(limiter.last_request, dict)
    assert limiter.last_request == {}


def test_rate_limiter_waits_when_called_too_soon(monkeypatch):
    """Rate limiter should sleep when the same domain is hit too quickly."""
    from bist_bot.data import fetcher as data_fetcher

    limiter = data_fetcher.RateLimiter()
    sleep_calls: list[float] = []
    clock = iter([100.0, 100.0, 101.0, 101.0, 103.0])

    monkeypatch.setattr(
        data_fetcher, "settings", data_fetcher.settings.replace(RATE_LIMIT_SECONDS=2.0)
    )
    monkeypatch.setattr(data_fetcher.time, "time", lambda: next(clock))
    monkeypatch.setattr(data_fetcher.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    limiter.wait_if_needed("borsaistanbul.com.tr")
    limiter.wait_if_needed("borsaistanbul.com.tr")

    assert sleep_calls == [1.0]


def test_clean_ticker_list_normalizes_and_deduplicates():
    """Ticker normalization should append .IS and remove duplicates."""
    from bist_bot.data.fetcher import (
        _clean_ticker_list,
        normalize_ticker,
        validate_data,
    )

    raw = ["thyao", "THYAO.IS", " asels ", "ASELS.IS", ""]

    assert _clean_ticker_list(raw) == ["THYAO.IS", "ASELS.IS"]
    assert normalize_ticker("garan") == "GARAN.IS"
    assert normalize_ticker("THYAO.IS") == "THYAO.IS"
    assert validate_data(pd.DataFrame()) is False


def test_fetcher_uses_injected_provider_for_history_and_batch():
    from bist_bot.data.fetcher import BISTDataFetcher

    class StubProvider:
        def fetch_history(self, ticker: str, period: str, interval: str):
            return pd.DataFrame(
                {
                    "open": [1, 1, 1, 1, 1],
                    "high": [2, 2, 2, 2, 2],
                    "low": [0.5, 0.5, 0.5, 0.5, 0.5],
                    "close": [1.5, 1.5, 1.5, 1.5, 1.5],
                    "volume": [100, 100, 100, 100, 100],
                },
                index=pd.date_range("2025-01-01", periods=5),
            )

        def fetch_batch(self, tickers: list[str], period: str, interval: str):
            frame = pd.DataFrame(
                {
                    "open": [1, 1, 1, 1, 1],
                    "high": [2, 2, 2, 2, 2],
                    "low": [0.5, 0.5, 0.5, 0.5, 0.5],
                    "close": [1.5, 1.5, 1.5, 1.5, 1.5],
                    "volume": [100, 100, 100, 100, 100],
                },
                index=pd.date_range("2025-01-01", periods=5),
            )
            return {ticker: frame for ticker in tickers}

        def fetch_quote(self, ticker: str):
            _ = ticker
            return None

        def fetch_universe(self, force_refresh: bool = False):
            _ = force_refresh
            return ["THYAO.IS", "ASELS.IS"]

    fetcher = BISTDataFetcher(watchlist=["THYAO.IS", "ASELS.IS"], provider=StubProvider())

    single = fetcher.fetch_single("THYAO.IS", force=True)
    batch = fetcher.fetch_all(period="1mo", interval="1d")

    assert single is not None
    assert set(batch) == {"THYAO.IS", "ASELS.IS"}


def test_fetcher_uses_provider_universe_when_watchlist_not_supplied():
    from bist_bot.data.fetcher import BISTDataFetcher

    class UniverseProvider:
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
            return [" thyao ", "ASELS.IS", "THYAO.IS"]

    fetcher = BISTDataFetcher(provider=UniverseProvider())

    assert fetcher.watchlist == ["THYAO.IS", "ASELS.IS"]


def test_fetcher_falls_back_to_static_universe_when_provider_universe_empty():
    from bist_bot.data.bist100 import BIST100_TICKERS
    from bist_bot.data.fetcher import BISTDataFetcher

    class EmptyUniverseProvider:
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
            return []

    fetcher = BISTDataFetcher(provider=EmptyUniverseProvider())

    assert fetcher.watchlist == BIST100_TICKERS


def test_fetcher_uses_provider_quote_fallback_before_history(monkeypatch):
    from bist_bot.data import fetcher as data_fetcher
    from bist_bot.data.fetcher import BISTDataFetcher

    class StubProvider:
        def fetch_history(self, ticker: str, period: str, interval: str):
            _ = ticker, period, interval
            return None

        def fetch_batch(self, tickers: list[str], period: str, interval: str):
            _ = tickers, period, interval
            return {}

        def fetch_quote(self, ticker: str):
            assert ticker == "THYAO.IS"
            return 111.0

        def fetch_universe(self, force_refresh: bool = False):
            _ = force_refresh
            return ["THYAO.IS"]

    class NullQuoteProvider:
        def fetch_quote(self, ticker: str):
            _ = ticker
            return None

    fetcher = BISTDataFetcher(provider=StubProvider(), quote_provider=NullQuoteProvider())
    monkeypatch.setattr(
        data_fetcher,
        "settings",
        data_fetcher.settings.replace(ENABLE_REALTIME_SCRAPING=True),
    )

    assert fetcher.get_current_price("THYAO.IS") == 111.0


def test_dependencies_selects_configured_data_provider():
    from bist_bot.config.settings import settings
    from bist_bot.data.providers import OfficialProviderStub, YFinanceProvider
    from bist_bot.dependencies import _build_data_provider

    with settings.override(DATA_PROVIDER="official_stub"):
        assert isinstance(_build_data_provider(), OfficialProviderStub)

    with settings.override(DATA_PROVIDER="yfinance"):
        assert isinstance(_build_data_provider(), YFinanceProvider)


def test_fetch_single_uses_cache_until_ttl_expires(monkeypatch):
    from bist_bot.data.fetcher import BISTDataFetcher

    class CountingProvider:
        def __init__(self):
            self.history_calls = 0

        def fetch_history(self, ticker: str, period: str, interval: str):
            self.history_calls += 1
            return pd.DataFrame(
                {
                    "open": [1, 1, 1, 1, 1],
                    "high": [2, 2, 2, 2, 2],
                    "low": [0.5, 0.5, 0.5, 0.5, 0.5],
                    "close": [1.5, 1.5, 1.5, 1.5, 1.5],
                    "volume": [100, 100, 100, 100, 100],
                },
                index=pd.date_range("2025-01-01", periods=5),
            )

        def fetch_batch(self, tickers: list[str], period: str, interval: str):
            _ = tickers, period, interval
            return {}

        def fetch_quote(self, ticker: str):
            _ = ticker
            return None

        def fetch_universe(self, force_refresh: bool = False):
            _ = force_refresh
            return ["THYAO.IS"]

    provider = CountingProvider()
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=provider)
    current_time = [pd.Timestamp("2025-01-01 10:00:00").to_pydatetime()]
    monkeypatch.setattr(fetcher, "_now", lambda: current_time[0])

    first = fetcher.fetch_single("THYAO.IS", period="1mo", interval="15m")
    current_time[0] = pd.Timestamp("2025-01-01 10:01:00").to_pydatetime()
    second = fetcher.fetch_single("THYAO.IS", period="1mo", interval="15m")
    current_time[0] = pd.Timestamp("2025-01-01 10:03:00").to_pydatetime()
    third = fetcher.fetch_single("THYAO.IS", period="1mo", interval="15m")

    assert first is not None
    assert second is not None
    assert third is not None
    assert provider.history_calls == 2


def test_fetch_single_force_refresh_bypasses_cache(monkeypatch):
    from bist_bot.data.fetcher import BISTDataFetcher

    class CountingProvider:
        def __init__(self):
            self.history_calls = 0

        def fetch_history(self, ticker: str, period: str, interval: str):
            self.history_calls += 1
            return pd.DataFrame(
                {
                    "open": [1, 1, 1, 1, 1],
                    "high": [2, 2, 2, 2, 2],
                    "low": [0.5, 0.5, 0.5, 0.5, 0.5],
                    "close": [1.5, 1.5, 1.5, 1.5, 1.5],
                    "volume": [100, 100, 100, 100, 100],
                },
                index=pd.date_range("2025-01-01", periods=5),
            )

        def fetch_batch(self, tickers: list[str], period: str, interval: str):
            _ = tickers, period, interval
            return {}

        def fetch_quote(self, ticker: str):
            _ = ticker
            return None

        def fetch_universe(self, force_refresh: bool = False):
            _ = force_refresh
            return ["THYAO.IS"]

    provider = CountingProvider()
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=provider)
    monkeypatch.setattr(
        fetcher, "_now", lambda: pd.Timestamp("2025-01-01 10:00:00").to_pydatetime()
    )

    fetcher.fetch_single("THYAO.IS", period="1mo", interval="15m")
    fetcher.fetch_single("THYAO.IS", period="1mo", interval="15m", force=True)

    assert provider.history_calls == 2


def test_fetch_all_recovers_partial_batch_failures_with_fallback():
    from bist_bot.app_metrics import render_metrics, reset_metrics
    from bist_bot.data.fetcher import BISTDataFetcher

    reset_metrics()

    frame = pd.DataFrame(
        {
            "open": [1, 1, 1, 1, 1],
            "high": [2, 2, 2, 2, 2],
            "low": [0.5, 0.5, 0.5, 0.5, 0.5],
            "close": [1.5, 1.5, 1.5, 1.5, 1.5],
            "volume": [100, 100, 100, 100, 100],
        },
        index=pd.date_range("2025-01-01", periods=5),
    )

    class PartialBatchProvider:
        def __init__(self):
            self.history_calls: list[str] = []

        def fetch_history(self, ticker: str, period: str, interval: str):
            _ = period, interval
            self.history_calls.append(ticker)
            return frame.copy()

        def fetch_batch(self, tickers: list[str], period: str, interval: str):
            _ = period, interval
            return {tickers[0]: frame.copy(), tickers[1]: None}

        def fetch_quote(self, ticker: str):
            _ = ticker
            return None

        def fetch_universe(self, force_refresh: bool = False):
            _ = force_refresh
            return ["THYAO.IS", "ASELS.IS"]

    provider = PartialBatchProvider()
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS", "ASELS.IS"],
        provider=provider,
    )

    results = fetcher.fetch_all(period="1mo", interval="1d", force=True)
    rendered_metrics = render_metrics()

    assert set(results) == {"THYAO.IS", "ASELS.IS"}
    assert provider.history_calls == ["ASELS.IS"]
    assert "bist_provider_fetch_outcome_success_total" in rendered_metrics
    assert "bist_provider_fetch_outcome_fallback_success_total" in rendered_metrics
    assert "bist_provider_fetch_coverage_pct 100.0" in rendered_metrics
