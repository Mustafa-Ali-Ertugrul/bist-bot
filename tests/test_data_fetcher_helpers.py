"""Tests for data fetcher helper functions."""

from __future__ import annotations

import pandas as pd

from bist_bot.data.helpers import (
    clean_ticker_list,
    normalize_ticker,
    validate_data,
)


def test_normalize_ticker_various_formats():
    """Ticker normalization handles various input formats."""
    assert normalize_ticker("thyao") == "THYAO.IS"
    assert normalize_ticker("THYAO.IS") == "THYAO.IS"
    assert normalize_ticker(" asels ") == "ASELS.IS"
    assert normalize_ticker("") == ""
    assert normalize_ticker("  ") == ""  # Only spaces becomes empty after strip
    assert normalize_ticker("akbnk") == "AKBNK.IS"


def test_clean_ticker_list_deduplicates_and_normalizes():
    """Ticker list cleaning removes duplicates and normalizes."""
    raw = ["thyao", "THYAO.IS", " asels ", "ASELS.IS", "", "  ", "akbnk", "AKBNK.IS"]
    expected = ["THYAO.IS", "ASELS.IS", "AKBNK.IS"]
    assert clean_ticker_list(raw) == expected


def test_clean_ticker_list_preserves_order():
    """Ticker list cleaning preserves first occurrence order."""
    raw = ["akbnk", "thyao", "AKBNK.IS", "THYAO.IS"]
    expected = ["AKBNK.IS", "THYAO.IS"]
    assert clean_ticker_list(raw) == expected


def test_validate_data_accepts_valid_dataframe():
    """Validation passes for proper OHLCV dataframe."""
    df = pd.DataFrame({
        'open': [10, 11, 12, 13, 14],
        'high': [12, 13, 14, 15, 16],
        'low': [9, 10, 11, 12, 13],
        'close': [11, 12, 13, 14, 15],
        'volume': [1000, 1100, 1200, 1300, 1400]
    })
    assert validate_data(df) is True


def test_validate_data_rejects_none():
    """Validation rejects None input."""
    assert validate_data(None) is False


def test_validate_data_rejects_empty():
    """Validation rejects empty dataframe."""
    df = pd.DataFrame()
    assert validate_data(df) is False


def test_validate_data_rejects_insufficient_rows():
    """Validation rejects dataframes with too few rows."""
    df = pd.DataFrame({
        'open': [10, 11],
        'high': [12, 13],
        'low': [9, 10],
        'close': [11, 12],
        'volume': [1000, 1100]
    })
    assert validate_data(df, min_rows=5) is False


def test_validate_data_rejects_mostly_null_rows():
    """Validation rejects dataframes with too many null rows."""
    df = pd.DataFrame({
        'open': [10, None, None],
        'high': [12, None, None],
        'low': [9, None, None],
        'close': [11, None, None],
        'volume': [1000, None, None]
    })
    # 2/3 rows are all null (>20%), should be rejected
    assert validate_data(df) is False


# Note: fetch_ohlcv and fetch_with_fallback require mocking yfinance
# We'll test them in integration tests with mocks in the BISTDataFetcher tests
