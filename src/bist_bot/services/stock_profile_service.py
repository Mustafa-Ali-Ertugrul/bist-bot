"""Faz 3: everything known about one symbol, computed from stored data only.

No network calls: the page reads ``daily_bars`` / ``fundamentals`` /
``scan_results``. Ratios are descriptive, never advice.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from bist_bot.config.settings import settings as default_settings
from bist_bot.data.isyatirim import statement_available_from
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
VALUATION_RANGE_DAYS: dict[str, int | None] = {
    "1y": 366,
    "3y": 1096,
    "5y": 1830,
    "all": None,
}

RETURN_WINDOWS: dict[str, int] = {"1w": 5, "1m": 21, "3m": 63, "1y": 252, "3y": 756}

# A BIST quarter is reported well after it closes; anything older than this is
# shown as late rather than silently presented as current.
FUNDAMENTALS_STALE_DAYS = 150


def period_end_date(period: str | None) -> date | None:
    """Last day of the reported quarter (``2026/06`` -> 2026-06-30)."""
    if not period:
        return None
    try:
        year, month = (int(part) for part in str(period).split("/"))
    except (TypeError, ValueError):
        return None
    if month == 3:
        return date(year, 3, 31)
    if month == 6:
        return date(year, 6, 30)
    if month == 9:
        return date(year, 9, 30)
    if month == 12:
        return date(year, 12, 31)
    return None


def fundamentals_stale(period: str | None, as_of: date | None = None) -> bool:
    """True when the newest report is old enough that the figures are dated.

    Age is measured from the quarter's close, against today unless a caller
    explicitly asks about another date. A lagging price series must not make an
    old balance sheet look fresh.
    """
    end = period_end_date(period)
    if end is None:
        return True
    reference = as_of or date.today()
    return (reference - end).days > FUNDAMENTALS_STALE_DAYS


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


def _ttm_at_period(
    statements: dict[str, dict[str, float]], item_code: str, year: int, month: int
) -> float | None:
    period = f"{year}/{month:02d}"
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


def _quarter_standalone(
    statements: dict[str, dict[str, float]], item_code: str, year: int, month: int
) -> float | None:
    period = f"{year}/{month:02d}"
    current = statements.get(period, {}).get(item_code)
    if current is None:
        return None
    if month == 3:
        return float(current)
    prev_period = f"{year}/{month - 3:02d}"
    prev_ytd = statements.get(prev_period, {}).get(item_code)
    if prev_ytd is None:
        return None
    return float(current) - float(prev_ytd)


def ttm_value(statements: dict[str, dict[str, float]], item_code: str) -> float | None:
    """Trailing twelve months for a YTD cumulative statement item.

    BIST statements are year-to-date, so TTM = latest YTD + previous full year
    - previous year's same YTD. December needs no adjustment.
    """
    periods = _sorted_periods(statements)
    if not periods:
        return None
    year, month, _ = periods[-1]
    return _ttm_at_period(statements, item_code, year, month)


def statement_view(statements: dict[str, dict[str, float]]) -> StatementView:
    periods = _sorted_periods(statements)
    quarters: list[dict[str, Any]] = []
    for year, month, period in periods[-8:]:
        sales_ytd = statements.get(period, {}).get("3C")
        profit_ytd = statements.get(period, {}).get("3Z")
        eq_val = statements.get(period, {}).get("2O")
        q_sales = _quarter_standalone(statements, "3C", year, month)
        q_profit = _quarter_standalone(statements, "3Z", year, month)
        q_ttm_sales = _ttm_at_period(statements, "3C", year, month)
        q_ttm_profit = _ttm_at_period(statements, "3Z", year, month)
        q_margin = (
            round(q_profit / q_sales * 100.0, 1)
            if q_sales is not None and q_sales > 0 and q_profit is not None
            else None
        )
        q_roe = (
            round(q_ttm_profit / float(eq_val) * 100.0, 1)
            if q_ttm_profit is not None and eq_val is not None and float(eq_val) > 0
            else None
        )
        quarters.append(
            {
                "period": period,
                "sales": sales_ytd,
                "net_profit": profit_ytd,
                "equity": eq_val,
                "q_sales": q_sales,
                "q_net_profit": q_profit,
                "q_net_margin_pct": q_margin,
                "ttm_sales": q_ttm_sales,
                "ttm_net_profit": q_ttm_profit,
                "roe_pct": q_roe,
            }
        )
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

    def profile(
        self, code: str, *, dividend_per_share: float | None = None
    ) -> dict[str, Any] | None:
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
            "dividend_yield_pct": None,
        }
        if market_cap and view.ttm_net_profit and view.ttm_net_profit > 0:
            ratios["pe_ttm"] = round(market_cap / view.ttm_net_profit, 2)
        if view.ttm_sales and view.ttm_sales > 0 and view.ttm_net_profit is not None:
            ratios["net_margin_pct"] = round(view.ttm_net_profit / view.ttm_sales * 100.0, 1)
        if market_cap and view.equity and view.equity > 0:
            ratios["pb"] = round(market_cap / view.equity, 2)
        if view.ttm_net_profit is not None and view.equity and view.equity > 0:
            ratios["roe_pct"] = round(view.ttm_net_profit / view.equity * 100.0, 1)
        if dividend_per_share and dividend_per_share > 0 and latest and latest.close > 0:
            ratios["dividend_yield_pct"] = round(dividend_per_share / latest.close * 100.0, 2)

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
                "period_end": (
                    period_end_date(view.latest_period).isoformat()
                    if period_end_date(view.latest_period)
                    else None
                ),
                "stale": fundamentals_stale(view.latest_period),
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

    def peers(self, code: str) -> dict[str, Any] | None:
        instrument = self._instrument(code)
        if instrument is None:
            return None
        sector = (instrument.sector or "").strip()
        dates = self.repository.list_snapshot_dates(limit=1)
        as_of_str = str(dates[0]["as_of"]) if dates else None
        if not sector or not as_of_str:
            return {
                "code": instrument.code,
                "sector": instrument.sector,
                "as_of": as_of_str,
                "peer_count": 0,
                "sufficient": False,
                "medians": {},
                "percentiles": {},
                "peers": [],
            }
        as_of = date.fromisoformat(as_of_str)
        instruments = {item.ticker: item for item in self.repository.list_instruments()}
        sector_key = sector.casefold()
        sector_rows = [
            row
            for row in self.repository.get_snapshots(as_of)
            if ((instruments.get(str(row["ticker"])) and instruments[str(row["ticker"])].sector) or "")
            .strip()
            .casefold()
            == sector_key
        ]
        self_row = next(
            (row for row in sector_rows if str(row["ticker"]) == instrument.ticker), None
        )
        metric_keys = (
            "pe_ttm",
            "pb",
            "roe_pct",
            "net_margin_pct",
            "ret_1m",
            "dividend_yield_pct",
        )
        sufficient = len(sector_rows) >= 3
        medians: dict[str, float | None] = {}
        percentiles: dict[str, int | None] = {}
        for key in metric_keys:
            vals = [
                float(row[key])
                for row in sector_rows
                if row.get(key) is not None
            ]
            if sufficient and vals:
                medians[key] = round(float(statistics.median(vals)), 2)
                own = self_row.get(key) if self_row else None
                if own is not None:
                    rank = sum(1 for v in vals if v <= float(own))
                    percentiles[key] = round(rank / len(vals) * 100.0)
                else:
                    percentiles[key] = None
            else:
                medians[key] = None
                percentiles[key] = None

        ordered_peers = sorted(
            sector_rows,
            key=lambda row: float(row.get("market_cap_tl") or 0.0),
            reverse=True,
        )[:6]
        peer_items: list[dict[str, Any]] = []
        for row in ordered_peers:
            inst = instruments.get(str(row["ticker"]))
            peer_items.append(
                {
                    "code": inst.code if inst else str(row["ticker"]).removesuffix(".IS"),
                    "name": inst.name if inst else "",
                    "is_self": str(row["ticker"]) == instrument.ticker,
                    "market_cap_tl": row.get("market_cap_tl"),
                    "pe_ttm": row.get("pe_ttm"),
                    "pb": row.get("pb"),
                    "roe_pct": row.get("roe_pct"),
                    "net_margin_pct": row.get("net_margin_pct"),
                    "ret_1m": row.get("ret_1m"),
                }
            )
        return {
            "code": instrument.code,
            "sector": instrument.sector,
            "as_of": as_of_str,
            "peer_count": len(sector_rows),
            "sufficient": sufficient,
            "medians": medians,
            "percentiles": percentiles,
            "peers": peer_items,
        }

    def valuation_history(self, code: str, range_key: str = "3y") -> dict[str, Any] | None:
        instrument = self._instrument(code)
        if instrument is None:
            return None
        days = VALUATION_RANGE_DAYS.get(range_key, VALUATION_RANGE_DAYS["3y"])
        start = None if days is None else date.today() - timedelta(days=days)
        bars = self.repository.get_bars(instrument.ticker, start=start)
        max_bars = max(100, int(getattr(self.settings, "STOCK_BARS_MAX", 2700)))
        if len(bars) > max_bars:
            bars = bars[-max_bars:]
        statements = self.repository.get_latest_statements(instrument.ticker)
        periods = _sorted_periods(statements)

        checkpoints: list[tuple[date, str, float | None, float | None]] = []
        for year, month, period in periods:
            avail = statement_available_from(year, month)
            ttm_np = _ttm_at_period(statements, "3Z", year, month)
            eq_raw = statements.get(period, {}).get("2O")
            eq_val = float(eq_raw) if eq_raw is not None else None
            checkpoints.append((avail, period, ttm_np, eq_val))
        checkpoints.sort(key=lambda item: item[0])

        series: list[dict[str, Any]] = []
        pe_vals: list[float] = []
        pb_vals: list[float] = []
        cp_idx = -1
        for bar in bars:
            while cp_idx + 1 < len(checkpoints) and checkpoints[cp_idx + 1][0] <= bar.date:
                cp_idx += 1
            pe_val: float | None = None
            pb_val: float | None = None
            active_period: str | None = None
            if cp_idx >= 0 and bar.market_cap_tl and bar.market_cap_tl > 0:
                _, active_period, ttm_np, eq_val = checkpoints[cp_idx]
                if ttm_np is not None and ttm_np > 0:
                    pe_val = round(bar.market_cap_tl / ttm_np, 2)
                    pe_vals.append(pe_val)
                if eq_val is not None and eq_val > 0:
                    pb_val = round(bar.market_cap_tl / eq_val, 2)
                    pb_vals.append(pb_val)
            series.append(
                {
                    "time": bar.date.isoformat(),
                    "pe_ttm": pe_val,
                    "pb": pb_val,
                    "period": active_period,
                }
            )

        def _band(vals: list[float], current: float | None) -> dict[str, float | None]:
            if not vals:
                return {"min": None, "median": None, "max": None, "current": current}
            return {
                "min": round(min(vals), 2),
                "median": round(float(statistics.median(vals)), 2),
                "max": round(max(vals), 2),
                "current": current,
            }

        last_pe = series[-1]["pe_ttm"] if series else None
        last_pb = series[-1]["pb"] if series else None
        return {
            "code": instrument.code,
            "range": range_key,
            "series": series,
            "pe_band": _band(pe_vals, last_pe),
            "pb_band": _band(pb_vals, last_pb),
        }

    # ------------------------------------------------------------------
    # Faz P3.2: side-by-side comparison
    # ------------------------------------------------------------------
    def compare(
        self, codes: list[str], *, range_key: str = "1y", max_codes: int = 4
    ) -> dict[str, Any]:
        cleaned: list[str] = []
        for raw in codes:
            code = (raw or "").strip().upper().removesuffix(".IS")
            if code and code not in cleaned:
                cleaned.append(code)
        cleaned = cleaned[:max_codes]
        days = RANGE_DAYS.get(range_key, RANGE_DAYS["1y"])
        cutoff = None if days is None else date.today() - timedelta(days=int(days))

        entries: list[dict[str, Any]] = []
        missing: list[str] = []
        for code in cleaned:
            instrument = self._instrument(code)
            if instrument is None:
                missing.append(code)
                continue
            # Metrics always use the full history: a short chart window must not
            # erase the 1y/3y return, the 52-week band or the 200-day average.
            history = self.repository.get_bars(instrument.ticker)
            bars = history if cutoff is None else [bar for bar in history if bar.date >= cutoff]
            if len(bars) < 2:
                missing.append(code)
                continue
            statements = self.repository.get_latest_statements(instrument.ticker)
            view = statement_view(statements)
            market_cap = history[-1].market_cap_tl if history else None
            pe_ttm = (
                round(market_cap / view.ttm_net_profit, 2)
                if market_cap and view.ttm_net_profit and view.ttm_net_profit > 0
                else None
            )
            pb = (
                round(market_cap / view.equity, 2)
                if market_cap and view.equity and view.equity > 0
                else None
            )
            roe = (
                round(view.ttm_net_profit / view.equity * 100.0, 1)
                if view.ttm_net_profit is not None and view.equity and view.equity > 0
                else None
            )
            entries.append(
                {
                    "code": instrument.code,
                    "name": instrument.name,
                    "sector": instrument.sector,
                    "bars": bars,
                    "returns": {
                        key: period_return(history, sessions)
                        for key, sessions in RETURN_WINDOWS.items()
                    },
                    "technical": technical_summary(history),
                    "fundamentals": {
                        "latest_period": view.latest_period,
                        "period_end": (
                            period_end_date(view.latest_period).isoformat()
                            if period_end_date(view.latest_period)
                            else None
                        ),
                        "stale": fundamentals_stale(view.latest_period),
                        "ttm_sales": view.ttm_sales,
                        "ttm_net_profit": view.ttm_net_profit,
                        "equity": view.equity,
                        "sales_growth_yoy_pct": view.sales_growth_yoy_pct,
                        "pe_ttm": pe_ttm,
                        "pb": pb,
                        "roe_pct": roe,
                    },
                }
            )

        # Normalise every series to 100 from the latest common session.
        common_dates: set[date] | None = None
        for entry in entries:
            dates = {bar.date for bar in entry["bars"]}
            common_dates = dates if common_dates is None else common_dates & dates
        base_date = min(common_dates) if common_dates else None

        series_out: list[dict[str, Any]] = []
        for entry in entries:
            base = None
            if base_date is not None:
                for bar in entry["bars"]:
                    if bar.date == base_date and bar.close > 0:
                        base = bar.close
                        break
            points = []
            for bar in entry["bars"]:
                if base is None or bar.close <= 0:
                    continue
                if base_date is not None and bar.date < base_date:
                    continue
                points.append(
                    {"time": bar.date.isoformat(), "value": round(bar.close / base * 100.0, 2)}
                )
            latest = entry["bars"][-1] if entry["bars"] else None
            previous = entry["bars"][-2] if len(entry["bars"]) > 1 else None
            series_out.append(
                {
                    "code": entry["code"],
                    "name": entry["name"],
                    "sector": entry["sector"],
                    "as_of": latest.date.isoformat() if latest else None,
                    "last_close": round(latest.close, 2) if latest else None,
                    "change_pct": _pct(
                        latest.close if latest else None,
                        previous.close if previous else None,
                    ),
                    "returns": entry["returns"],
                    "technical": entry["technical"],
                    "fundamentals": entry["fundamentals"],
                    "series": points,
                }
            )
        return {
            "range": range_key,
            "base_date": base_date.isoformat() if base_date else None,
            "stocks": series_out,
            "missing": missing,
        }