"""Ticker normalization and raw history fetch helpers."""

from __future__ import annotations

import logging
from typing import Protocol

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class RateLimiterProtocol(Protocol):
    def wait_if_needed(self, domain: str) -> None: ...


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
    if df.isnull().all(axis=1).mean() > 0.20:
        return False
    return True


def fetch_ohlcv(ticker: str, period: str, interval: str, rate_limiter: RateLimiterProtocol) -> pd.DataFrame | None:
    """Fetch raw OHLCV data from yfinance."""
    rate_limiter.wait_if_needed("yahoo.finance")
    stock = yf.Ticker(ticker)
    return stock.history(period=period, interval=interval)


def fetch_with_fallback(ticker: str, period: str, interval: str, rate_limiter: RateLimiterProtocol) -> pd.DataFrame | None:
    """Fetch data safely, logging failures and returning ``None`` on error."""
    normalized_ticker = normalize_ticker(ticker)
    try:
        df = fetch_ohlcv(normalized_ticker, period=period, interval=interval, rate_limiter=rate_limiter)
        if not validate_data(df):
            logger.warning("⚠️ %s icin bos veya yetersiz veri dondu", normalized_ticker)
            return None
        return df
    except Exception as exc:
        logger.error("❌ %s veri cekilemedi: %s", normalized_ticker, exc)
        return None
