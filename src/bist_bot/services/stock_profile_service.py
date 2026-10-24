"""Faz 3: everything known about one symbol, computed from stored data only.

No network calls: the page reads ``daily_bars`` / ``fundamentals`` /
``scan_results``. Ratios are descriptive, never advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.indicators import TechnicalIndicators

RANGE_DAYS: dict[str, int | None] = {
    "1m": 31,
    "3m": 92,
    "1y": 366,
    "5y": 1830,
    "all": None,
}

RETURN_WINDOWS: dict[str, int] = {"1w": 5, "1m": 21, "3m": 63, "1y": 252, "3y": 756}


@dataclass(frozen=True)
class StatementView:
    """Latest published quarter plus the derived trailing-twelve-month values."""

    latest_period: str | None
    quarters: list[dict[str, Any]]
    ttm_sales: float | None
    ttm_net_profit: float | None
    equity: float | None
    sales_growth_yoy_pct: float | None


def _pct(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round((current / base - 1.0) * 100.0, 2)


def _sorted_periods(statements: dict[str, dict[str, float]]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for period in statements:
        try:
            year, month = (int(part) for part in period.split("/"))
        except ValueError:
            continue
        if month in (3, 6, 9, 12):
            out.append((year, month, period))
    return sorted(out)


def ttm_value(statements: dict[str, dict[str, float]], item_code: str) -> float | None:
    """Trailing twelve months for a YTD cumulative statement item.

    BIST statements are year-to-date, so TTM = latest YTD + previous full year
    - previous year's same YTD. December needs no adjustment.
    """
    periods = _sorted_periods(statements)
    if not periods:
        return None
    year, month, period = periods[-1]
    current = statements.get(period, {}).get(item_code)
    if current is None:
        return None
    if month == 12:
        return float(current)
    previous_annual = statements.get(f"{year - 1}/12", {}).get(item_code)
    previous_same = statements.get(f"{year - 1}/{month:02d}", {}).get(item_code)
    if previous_annual is None or previous_same is None:
        return None
    return float(current) + float(previous_annual) - float(previous_same)


def statement_view(statements: dict[str, dict[str, float]]) -> StatementView:
    periods = _sorted_periods(statements)
    quarters = [
        {
            "period": period,
            "sales": statements.get(period, {}).get("3C"),
            "net_profit": statements.get(period, {}).get("3Z"),
            "equity": statements.get(period, {}).get("2O"),
        }
        for _, _, period in periods[-8:]
    ]
    growth: float | None = None
    if periods:
        year, month, period = periods[-1]
        current = statements.get(period, {}).get("3C")
        previous = statements.get(f"{year - 1}/{month:02d}", {}).get("3C")
        if current is not None and previous is not None and previous > 0:
            growth = round((float(current) - float(previous)) / float(previous) * 100.0, 1)
    equity = statements.get(periods[-1][2], {}).get("2O") if periods else None
    return StatementView(
        latest_period=periods[-1][2] if periods else None,
        quarters=quarters,
        ttm_sales=ttm_value(statements, "3C"),
        ttm_net_profit=ttm_value(statements, "3Z"),
        equity=float(equity) if equity is not None else None,
        sales_growth_yoy_pct=growth,
    )


def _price_series(bars: list[DailyBar]) -> pd.Series:
    return pd.Series(
        [bar.close for bar in bars],
        index=pd.to_datetime([bar.date for bar in bars]),
        dtype="float64",
    )


def period_return(bars: list[DailyBar], sessions: int) -> float | None:
    """Return over the last ``sessions`` bars, or None when history is short."""
    if len(bars) <= sessions:
        return None
    return _pct(bars[-1].close, bars[-1 - sessions].close)


def return_since(bars: list[DailyBar], target: date) -> float | None:
    """Return from the last session at/before ``target`` to the latest close."""
    base: float | None = None
    for bar in bars:
        if bar.date <= target:
            base = bar.close
        else:
            break
    return _pct(bars[-1].close, base) if base is not None else None


def technical_summary(bars: list[DailyBar]) -> dict[str, float | None]:
    if not bars:
        return {}
    closes = _price_series(bars)
    frame = TechnicalIndicators.add_rsi(pd.DataFrame({"close": closes}), in_place=True)
    rsi = frame["rsi"].iloc[-1]
    sma50 = closes.rolling(50, min_periods=50).mean().iloc[-1]
    sma200 = closes.rolling(200, min_periods=200).mean().iloc[-1]
    window = closes.iloc[-252:]
    high_52w = float(window.max())
    low_52w = float(window.min())
    volumes = [bar.volume_tl for bar in bars[-20:] if bar.volume_tl is not None]
    close = bars[-1].close
    return {
        "rsi14": None if pd.isna(rsi) else round(float(rsi), 1),
        "sma50": None if pd.isna(sma50) else round(float(sma50), 2),
        "sma200": None if pd.isna(sma200) else round(float(sma200), 2),
        "vs_sma50_pct": _pct(close, None if pd.isna(sma50) else float(sma50)),
        "vs_sma200_pct": _pct(close, None if pd.isna(sma200) else float(sma200)),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "from_high_pct": _pct(close, high_52w),
        "from_low_pct": _pct(close, low_52w),
        "avg_volume_20": round(sum(volumes) / len(volumes), 0) if volumes else None,
    }


def snapshot_row(
    ticker: str,
    bars: list[DailyBar],
    statements: dict[str, dict[str, float]],
    dividend_per_share: float | None = None,
) -> dict[str, object] | None:
    """One screener row (Faz 4) from the same numbers the stock page shows."""
    if not bars:
        return None
    technical = technical_summary(bars)
    view = statement_view(statements)
    latest = bars[-1]
    previous = bars[-2] if len(bars) > 1 else None
    market_cap = latest.market_cap_tl

    pe_ttm = None
    if market_cap and view.ttm_net_profit and view.ttm_net_profit > 0:
        pe_ttm = round(market_cap / view.ttm_net_profit, 2)
    pb = None
    if market_cap and view.equity and view.equity > 0:
        pb = round(market_cap / view.equity, 2)
    net_margin = None
    if view.ttm_sales and view.ttm_sales > 0 and view.ttm_net_profit is not None:
        net_margin = round(view.ttm_net_profit / view.ttm_sales * 100.0, 1)
    roe = None
    if view.ttm_net_profit is not None and view.equity and view.equity > 0:
        roe = round(view.ttm_net_profit / view.equity * 100.0, 1)
    dividend_yield = None
    if dividend_per_share and dividend_per_share > 0 and latest.close > 0:
        dividend_yield = round(dividend_per_share / latest.close * 100.0, 2)

    return {
        "ticker": ticker,
        "close": round(latest.close, 4),
        "change_pct": _pct(latest.close, previous.close if previous else None),
        "ret_1m": period_return(bars, 21),
        "ret_3m": period_return(bars, 63),
        "ret_1y": period_return(bars, 252),
        "rsi14": technical.get("rsi14"),
        "sma50_gap_pct": technical.get("vs_sma50_pct"),
        "sma200_gap_pct": technical.get("vs_sma200_pct"),
        "from_52w_high_pct": technical.get("from_high_pct"),
        "avg_volume_20": technical.get("avg_volume_20"),
        "market_cap_tl": market_cap,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "net_margin_pct": net_margin,
        "roe_pct": roe,
        "sales_growth_yoy_pct": view.sales_growth_yoy_pct,
        "dividend_yield_pct": dividend_yield,
        "fundamentals_period": view.latest_period,
    }


class StockProfileService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings

    def search(self, query: str, limit: int = 20) -> list[dict[str, str | None]]:
        if not (query or "").strip():
            return []
        return [
            {"code": item.code, "name": item.name, "sector": item.sector}
            for item in self.repository.search_instruments(query, limit=limit)
        ]

    def _instrument(self, code: str) -> Instrument | None:
        return self.repository.get_instrument(code)

    def bars(self, code: str, range_key: str = "1y") -> list[dict[str, Any]] | None:
        instrument = self._instrument(code)
        if instrument is None:
            return None
        days = RANGE_DAYS.get(range_key, RANGE_DAYS["1y"])
        start = None if days is None else date.today() - timedelta(days=days)
        bars = self.repository.get_bars(instrument.ticker, start=start)
        max_bars = max(100, int(getattr(self.settings, "STOCK_BARS_MAX", 2700)))
        if len(bars) > max_bars:
            bars = bars[-max_bars:]
        if not bars:
            return []
        return [
            {
                "time": bar.date.isoformat(),
                "close": round(bar.close, 4),
                "volume": bar.volume_tl,
            }
            for bar in bars
        ]

    def fundamentals(self, code: str) -> dict[str, Any] | None:
        instrument = self._instrument(code)
        if instrument is None:
            return None
        statements = self.repository.get_latest_statements(instrument.ticker)
        view = statement_view(statements)
        return {
            "latest_period": view.latest_period,
            "quarters": view.quarters,
            "ttm": {"sales": view.ttm_sales, "net_profit": view.ttm_net_profit},
            "equity": view.equity,
            "sales_growth_yoy_pct": view.sales_growth_yoy_pct,
        }

    def profile(self, code: str) -> dict[str, Any] | None:
        instrument = self._instrument(code)
        if instrument is None:
            return None
        bars = self.repository.get_bars(instrument.ticker)
        statements = self.repository.get_latest_statements(instrument.ticker)
        view = statement_view(statements)

        latest = bars[-1] if bars else None
        previous = bars[-2] if len(bars) > 1 else None
        market_cap = latest.market_cap_tl if latest else None

        returns: dict[str, float | None] = {
            key: period_return(bars, sessions) for key, sessions in RETURN_WINDOWS.items()
        }
        if latest is not None:
            returns["ytd"] = return_since(bars, date(latest.date.year - 1, 12, 31))

        ratios: dict[str, float | None] = {
            "pe_ttm": None,
            "net_margin_pct": None,
            "pb": None,
            "roe_pct": None,
            "sales_growth_yoy_pct": view.sales_growth_yoy_pct,
        }
        if market_cap and view.ttm_net_profit and view.ttm_net_profit > 0:
            ratios["pe_ttm"] = round(market_cap / view.ttm_net_profit, 2)
        if view.ttm_sales and view.ttm_sales > 0 and view.ttm_net_profit is not None:
            ratios["net_margin_pct"] = round(view.ttm_net_profit / view.ttm_sales * 100.0, 1)
        if market_cap and view.equity and view.equity > 0:
            ratios["pb"] = round(market_cap / view.equity, 2)
        if view.ttm_net_profit is not None and view.equity and view.equity > 0:
            ratios["roe_pct"] = round(view.ttm_net_profit / view.equity * 100.0, 1)

        return {
            "code": instrument.code,
            "name": instrument.name,
            "sector": instrument.sector,
            "as_of": latest.date.isoformat() if latest else None,
            "last_close": round(latest.close, 2) if latest else None,
            "previous_close": round(previous.close, 2) if previous else None,
            "change_pct": _pct(
                latest.close if latest else None, previous.close if previous else None
            ),
            "market_cap_tl": market_cap,
            "returns": returns,
            "technical": technical_summary(bars),
            "fundamentals": {
                "latest_period": view.latest_period,
                "ttm_sales": view.ttm_sales,
                "ttm_net_profit": view.ttm_net_profit,
                "equity": view.equity,
                "ratios": ratios,
            },
        }

    def scans(self, code: str, days: int = 30) -> list[dict[str, Any]] | None:
        instrument = self._instrument(code)
        if instrument is None:
            return None
        return self.repository.get_scan_hits_for_ticker(instrument.ticker, days=days)
