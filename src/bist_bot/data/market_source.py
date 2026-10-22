"""Faz 7: swap the market-data vendor without touching the ingestion services.

The Is Yatırım implementation is the current development source. A licensed
vendor adapter implements the same protocol; nothing else in the pipeline
changes except configuration.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import pandas as pd
import requests

from bist_bot.data import isyatirim


class MarketDataSource(Protocol):
    name: str

    def fetch_universe(self, session: requests.Session) -> list[dict[str, str]]: ...

    def fetch_daily(
        self, code: str, start: date, end: date, session: requests.Session
    ) -> pd.DataFrame: ...

    def fetch_index_daily(
        self, session: requests.Session, start: date, end: date, proxy_ticker: str
    ) -> pd.DataFrame: ...

    def fetch_statements(
        self, code: str, quarters: list[tuple[int, int]], session: requests.Session
    ) -> dict[str, dict[str, float]]: ...

    def published_quarters(self, as_of: date, count: int) -> list[tuple[int, int]]: ...


class IsYatirimSource:
    """Delegates to ``data.isyatirim`` at call time (so tests can patch it)."""

    name = "isyatirim"

    def fetch_universe(self, session: requests.Session) -> list[dict[str, str]]:
        return isyatirim.fetch_universe(session)

    def fetch_daily(
        self, code: str, start: date, end: date, session: requests.Session
    ) -> pd.DataFrame:
        return isyatirim.fetch_daily(code, start, end, session)

    def fetch_index_daily(
        self, session: requests.Session, start: date, end: date, proxy_ticker: str
    ) -> pd.DataFrame:
        return isyatirim.fetch_index_daily(session, start, end, proxy_ticker=proxy_ticker)

    def fetch_statements(
        self, code: str, quarters: list[tuple[int, int]], session: requests.Session
    ) -> dict[str, dict[str, float]]:
        return isyatirim.fetch_statements(code, quarters, session)

    def published_quarters(self, as_of: date, count: int) -> list[tuple[int, int]]:
        return isyatirim.published_quarters(as_of, count)


def build_market_source(settings: Any) -> MarketDataSource:
    name = str(getattr(settings, "MARKET_DATA_SOURCE", "isyatirim") or "isyatirim").lower()
    if name == "isyatirim":
        return IsYatirimSource()
    raise ValueError(
        f"MARKET_DATA_SOURCE={name!r} için adaptör yok. Lisanslı sağlayıcı sözleşmesi "
        "ve API dokümanı geldiğinde burada tanımlanır."
    )


__all__ = ["IsYatirimSource", "MarketDataSource", "build_market_source"]
