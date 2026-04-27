from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pandas as pd


class FetchTracker:
    def __init__(self):
        self.fetched_tickers = []

    def record_fetch(self, ticker, period, interval, force=False, validate=True):
        self.fetched_tickers.append(ticker)
        return pd.DataFrame(
            {
                "open": [1.0, 2.0],
                "high": [1.5, 2.5],
                "low": [0.5, 1.5],
                "close": [1.2, 2.2],
                "volume": [100, 200],
            },
            index=pd.date_range("2025-01-01", periods=2),
        )


def test_fetch_multi_timeframe_only_fetches_requested_tickers():
    from bist_bot.data.fetcher import BISTDataFetcher

    tracker = FetchTracker()

    class MockProvider:
        def fetch_universe(self):
            return ["THYAO.IS", "ASELS.IS", "GARAN.IS"]

        def fetch_batch(self, tickers, period, interval):
            return {}

        def fetch_quote(self, ticker):
            return 10.0

    class MockQuoteProvider:
        def fetch_quote(self, ticker):
            return 10.0

    fetcher = BISTDataFetcher.__new__(BISTDataFetcher)
    fetcher.provider = MockProvider()
    fetcher.quote_provider = MockQuoteProvider()
    fetcher.watchlist = ["THYAO.IS", "ASELS.IS", "GARAN.IS"]
    fetcher._history_cache = {}
    fetcher._analysis_cache = {}
    fetcher._quote_cache = {}

    fetcher.fetch_single = tracker.record_fetch

    result = fetcher.fetch_multi_timeframe(["THYAO.IS", "GARAN.IS"], validate=False)

    assert set(result.keys()) == {"THYAO.IS", "GARAN.IS"}
    assert tracker.fetched_tickers.count("THYAO.IS") == 2
    assert tracker.fetched_tickers.count("GARAN.IS") == 2
    assert "ASELS.IS" not in tracker.fetched_tickers


def test_fetch_multi_timeframe_all_fetches_full_watchlist():
    from bist_bot.data.fetcher import BISTDataFetcher

    tracker = FetchTracker()

    class MockProvider:
        def fetch_universe(self):
            return ["THYAO.IS", "ASELS.IS"]

        def fetch_batch(self, tickers, period, interval):
            return {}

        def fetch_quote(self, ticker):
            return 10.0

    class MockQuoteProvider:
        def fetch_quote(self, ticker):
            return 10.0

    fetcher = BISTDataFetcher.__new__(BISTDataFetcher)
    fetcher.provider = MockProvider()
    fetcher.quote_provider = MockQuoteProvider()
    fetcher.watchlist = ["THYAO.IS", "ASELS.IS"]
    fetcher._history_cache = {}
    fetcher._analysis_cache = {}
    fetcher._quote_cache = {}

    fetcher.fetch_single = tracker.record_fetch
    fetcher.fetch_all = lambda period=None, interval=None, force=False, validate=True: {
        t: tracker.record_fetch(t, period, interval) for t in fetcher.watchlist
    }

    result = fetcher.fetch_multi_timeframe_all(validate=False)

    assert set(result.keys()) == {"THYAO.IS", "ASELS.IS"}
