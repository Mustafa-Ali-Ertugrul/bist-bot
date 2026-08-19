"""Fundamentals quick-screening helpers (PE ratio, market cap, sector).

This module turns the fetcher's ``get_stock_info`` payload into a sortable
fundamental screen without touching the real-time scan pipeline. It is
deliberately small and self-contained: no DB writes, no network calls here —
all data comes from the injected fetcher.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FundamentalRow:
    """One ticker's fundamental snapshot used for screening."""

    ticker: str
    name: str
    sector: str
    market_cap: float
    pe_ratio: float
    high_52w: float | None
    low_52w: float | None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def screen_fundamentals(
    fetcher: Any,
    tickers: list[str],
    *,
    max_pe: float | None = None,
    min_market_cap_tl: float | None = None,
    include_negative_pe: bool = False,
) -> list[FundamentalRow]:
    """Fetch and screen fundamentals, sorted by PE ratio ascending.

    Filtering:
    - Rows without a usable PE ratio are dropped (negative PE is excluded
      unless ``include_negative_pe`` is set).
    - ``max_pe`` drops richly valued names (e.g. ``max_pe=25``).
    - ``min_market_cap_tl`` drops small caps (values in TL; yfinance reports
      marketCap in USD, so callers on BIST should scale accordingly or pass
      0.0 to disable).
    """
    rows: list[FundamentalRow] = []
    for ticker in tickers:
        info = fetcher.get_stock_info(ticker) or {}
        pe = _optional_float(info.get("pe_ratio"))
        if pe is None or (not include_negative_pe and pe <= 0):
            continue
        if max_pe is not None and pe > max_pe:
            continue
        market_cap = float(info.get("market_cap") or 0.0)
        if min_market_cap_tl is not None and market_cap < min_market_cap_tl:
            continue
        rows.append(
            FundamentalRow(
                ticker=ticker,
                name=str(info.get("name") or ticker),
                sector=str(info.get("sector") or "Bilinmiyor"),
                market_cap=market_cap,
                pe_ratio=pe,
                high_52w=_optional_float(info.get("52w_high")),
                low_52w=_optional_float(info.get("52w_low")),
            )
        )
    return sorted(rows, key=lambda row: row.pe_ratio)


def format_fundamentals_table(rows: list[FundamentalRow], limit: int | None = 20) -> str:
    """Render a compact text table with the most attractive names first."""
    if not rows:
        return "Uygun temel veri bulunamadı (PE > 0 koşulu sağlanmıyor)."
    visible = rows if limit is None else rows[:limit]
    lines = [
        f"{'Ticker':<12} {'PE':>8} {'Piyasa Dğ.':>14} {'Sektör':<24} {'Ad':<24}",
        "-" * 90,
    ]
    for row in visible:
        cap_text = f"{row.market_cap / 1_000_000_000:,.2f} Mr $" if row.market_cap else "-"
        lines.append(
            f"{row.ticker:<12} {row.pe_ratio:>8.1f} {cap_text:>14} {row.sector:<24} {row.name:<24}"
        )
    if limit is not None and len(rows) > limit:
        lines.append(f"... toplam {len(rows)} hisse (ilk {limit} gösteriliyor)")
    return "\n".join(lines)


def save_fundamentals_csv(rows: list[FundamentalRow], path: str) -> None:
    """Persist the screen output as UTF-8 CSV."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["ticker", "name", "sector", "market_cap", "pe_ratio", "52w_high", "52w_low"]
        )
        for row in rows:
            writer.writerow(
                [
                    row.ticker,
                    row.name,
                    row.sector,
                    row.market_cap,
                    row.pe_ratio,
                    row.high_52w if row.high_52w is not None else "",
                    row.low_52w if row.low_52w is not None else "",
                ]
            )
