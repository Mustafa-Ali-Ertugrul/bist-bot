"""Ticker normalization and dataframe validation helpers."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class HistoryProviderProtocol(Protocol):
    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None: ...


def normalize_ticker(ticker: str) -> str:
    """Normalize a single ticker into uppercase BIST format."""
    normalized = ticker.strip().upper()
    if not normalized:
        return ""
    if not normalized.endswith(".IS"):
        normalized = normalized + ".IS"
    return normalized


def clean_ticker_list(tickers: list[str]) -> list[str]:
    """Normalize ticker symbols and remove duplicates."""
    seen = set()
    result = []
    for raw_ticker in tickers:
        ticker = normalize_ticker(raw_ticker)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        result.append(ticker)
    return result


def validate_data(df: pd.DataFrame | None, min_rows: int = 5) -> bool:
    """Validate downloaded OHLCV data before normalization."""
    if df is None or df.empty:
        return False
    if len(df) < min_rows:
        return False
    return not df.isnull().all(axis=1).mean() > 0.2


def fetch_history_with_provider(
    provider: HistoryProviderProtocol, ticker: str, period: str, interval: str
) -> pd.DataFrame | None:
    normalized_ticker = normalize_ticker(ticker)
    df = provider.fetch_history(normalized_ticker, period=period, interval=interval)
    if not validate_data(df):
        return None
    return df
