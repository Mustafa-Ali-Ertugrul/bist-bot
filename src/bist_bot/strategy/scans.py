"""Faz 2: pure, look-ahead-free screen definitions over stored daily bars.

Every scan only sees bars up to ``as_of`` and statement periods that were
published by ``as_of``. Scans never emit buy/sell instructions: they return
"this symbol matched this rule with this value", and the UI decides what to
show. The live 15m StrategyEngine is deliberately not reused.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

from bist_bot.data.isyatirim import statement_available_from
from bist_bot.db.repositories.market_data_repository import DailyBar
from bist_bot.indicators import TechnicalIndicators

# Bars needed before a rule may fire; keeps min_periods=1 style shortcuts from
# inventing crosses on a short history.
MIN_BARS = {
    "rsi_dip": 20,
    "sma_5_22": 23,
    "sma_50_200": 201,
    "hacim_sok": 21,
    "zirve_52h": 253,
    "bb_sikisma": 141,
}


@dataclass(frozen=True)
class ScanHit:
    value: float
    detail: str


@dataclass(frozen=True)
class ScanDefinition:
    code: str
    title: str
    description: str
    kind: str  # "technical" | "fundamental"
    rule: Callable[[Sequence[DailyBar], date, FundamentalContext], ScanHit | None]


@dataclass(frozen=True)
class FundamentalContext:
    """Published statements plus the split-adjusted market cap of ``as_of``."""

    statements: dict[str, dict[str, float]]
    market_cap_tl: float | None
    dividend_yield_pct: float | None = None

    def annual_net_profit(self, as_of: date) -> tuple[int, float] | None:
        """Latest December net profit (``3Z``) whose statement is public by ``as_of``."""
        best: tuple[int, float] | None = None
        for period, items in self.statements.items():
            try:
                year = int(period.split("/")[0])
                month = int(period.split("/")[1])
            except (IndexError, ValueError):
                continue
            if month != 12 or statement_available_from(year, 12) > as_of:
                continue
            net = items.get("3Z")
            if net is None:
                continue
            if best is None or year > best[0]:
                best = (year, float(net))
        return best


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frame(bars: Sequence[DailyBar]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "close": [bar.close for bar in bars],
            "volume": [bar.volume_tl or 0.0 for bar in bars],
        },
        index=pd.to_datetime([bar.date for bar in bars]),
    )
    return frame


def _crosses_up(fast: pd.Series, slow: pd.Series) -> bool:
    if len(fast) < 2 or len(slow) < 2:
        return False
    if pd.isna(fast.iloc[-2]) or pd.isna(slow.iloc[-2]):
        return False
    if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]):
        return False
    return bool(fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1])


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


# ---------------------------------------------------------------------------
# Technical rules
# ---------------------------------------------------------------------------


def scan_rsi_dip(
    bars: Sequence[DailyBar], _as_of: date, _ctx: FundamentalContext
) -> ScanHit | None:
    if len(bars) < MIN_BARS["rsi_dip"]:
        return None
    frame = TechnicalIndicators.add_rsi(_frame(bars), in_place=True)
    value = frame["rsi"].iloc[-1]
    if pd.isna(value) or value >= 30:
        return None
    return ScanHit(value=round(float(value), 2), detail=f"RSI(14) {value:.1f} < 30")


def scan_sma_5_22(
    bars: Sequence[DailyBar], _as_of: date, _ctx: FundamentalContext
) -> ScanHit | None:
    if len(bars) < MIN_BARS["sma_5_22"]:
        return None
    closes = _frame(bars)["close"]
    fast, slow = _sma(closes, 5), _sma(closes, 22)
    if not _crosses_up(fast, slow):
        return None
    return ScanHit(
        value=round(float(fast.iloc[-1]), 4),
        detail=f"SMA5 {fast.iloc[-1]:.2f} > SMA22 {slow.iloc[-1]:.2f} (ilk gün)",
    )


def scan_sma_50_200(
    bars: Sequence[DailyBar], _as_of: date, _ctx: FundamentalContext
) -> ScanHit | None:
    if len(bars) < MIN_BARS["sma_50_200"]:
        return None
    closes = _frame(bars)["close"]
    fast, slow = _sma(closes, 50), _sma(closes, 200)
    if not _crosses_up(fast, slow):
        return None
    return ScanHit(
        value=round(float(fast.iloc[-1]), 4),
        detail=f"SMA50 {fast.iloc[-1]:.2f} > SMA200 {slow.iloc[-1]:.2f} (ilk gün)",
    )


def scan_volume_shock(
    bars: Sequence[DailyBar], _as_of: date, _ctx: FundamentalContext
) -> ScanHit | None:
    if len(bars) < MIN_BARS["hacim_sok"]:
        return None
    volumes = _frame(bars)["volume"]
    average = float(volumes.iloc[-21:-1].mean())
    if average <= 0:
        return None
    ratio = float(volumes.iloc[-1]) / average
    if ratio < 2.0:
        return None
    return ScanHit(value=round(ratio, 2), detail=f"Hacim 20g ortalamanın {ratio:.1f}x")


def scan_52w_high(
    bars: Sequence[DailyBar], _as_of: date, _ctx: FundamentalContext
) -> ScanHit | None:
    if len(bars) < MIN_BARS["zirve_52h"]:
        return None
    closes = _frame(bars)["close"]
    previous_high = float(closes.iloc[-253:-1].max())
    close = float(closes.iloc[-1])
    if close <= previous_high:
        return None
    return ScanHit(
        value=round(close, 4),
        detail=f"Kapanış {close:.2f} > 52 hafta zirvesi {previous_high:.2f}",
    )


def scan_bollinger_squeeze(
    bars: Sequence[DailyBar], _as_of: date, _ctx: FundamentalContext
) -> ScanHit | None:
    if len(bars) < MIN_BARS["bb_sikisma"]:
        return None
    closes = _frame(bars)["close"]
    middle = _sma(closes, 20)
    deviation = closes.rolling(window=20, min_periods=20).std(ddof=0)
    width = (4 * deviation) / middle
    width = width.dropna()
    if len(width) < 121:
        return None
    current = float(width.iloc[-1])
    percentile = float(width.iloc[-121:-1].quantile(0.10))
    if current > percentile:
        return None
    return ScanHit(
        value=round(current, 4),
        detail=f"Bant genişliği {current:.3f}, son 120 günün en dar %10'unda",
    )


# ---------------------------------------------------------------------------
# Fundamental rules (published periods only)
# ---------------------------------------------------------------------------


def scan_cheap_profitable(
    bars: Sequence[DailyBar], as_of: date, ctx: FundamentalContext
) -> ScanHit | None:
    if not bars:
        return None
    net = ctx.annual_net_profit(as_of)
    market_cap = bars[-1].market_cap_tl or ctx.market_cap_tl
    if net is None or not market_cap or market_cap <= 0:
        return None
    year, profit = net
    if profit <= 0:
        return None
    pe = float(market_cap) / profit
    if not 0 < pe <= 10:
        return None
    return ScanHit(value=round(pe, 2), detail=f"F/K {pe:.1f} ({year} net kârı)")


def scan_sales_growth(
    _bars: Sequence[DailyBar], as_of: date, ctx: FundamentalContext
) -> ScanHit | None:
    published: list[tuple[int, int]] = []
    for period in ctx.statements:
        try:
            year, month = (int(part) for part in period.split("/"))
        except ValueError:
            continue
        if month in (3, 6, 9, 12) and statement_available_from(year, month) <= as_of:
            published.append((year, month))
    if not published:
        return None
    year, month = max(published)
    current = ctx.statements.get(f"{year}/{month:02d}", {}).get("3C")
    previous = ctx.statements.get(f"{year - 1}/{month:02d}", {}).get("3C")
    if current is None or previous is None or previous <= 0:
        return None
    growth = (float(current) - float(previous)) / float(previous) * 100.0
    if growth < 20:
        return None
    return ScanHit(
        value=round(growth, 1),
        detail=f"Satışlar {year}/{month:02d} çeyreğinde yıllık %{growth:.1f}",
    )


def scan_dividend_yield(
    _bars: Sequence[DailyBar], _as_of: date, ctx: FundamentalContext
) -> ScanHit | None:
    """Gross trailing-12-month cash dividend yield of at least 4%."""
    yield_pct = ctx.dividend_yield_pct
    if yield_pct is None or yield_pct < 4.0:
        return None
    return ScanHit(
        value=round(float(yield_pct), 2),
        detail=f"Son 12 ay brüt nakit temettü verimi %{yield_pct:.2f}",
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SCANS: tuple[ScanDefinition, ...] = (
    ScanDefinition(
        "rsi_dip",
        "RSI Dip",
        "RSI(14) 30'un altına inen hisseler.",
        "technical",
        scan_rsi_dip,
    ),
    ScanDefinition(
        "sma_5_22",
        "5-22 Kesişimi",
        "5 günlük ortalama 22 günlük ortalamayı yukarı kesenler.",
        "technical",
        scan_sma_5_22,
    ),
    ScanDefinition(
        "sma_50_200",
        "50-200 Kesişimi",
        "50 günlük ortalama 200 günlük ortalamayı yukarı kesenler (golden cross).",
        "technical",
        scan_sma_50_200,
    ),
    ScanDefinition(
        "hacim_sok",
        "Hacim Şoku",
        "Hacmi 20 günlük ortalamanın en az 2 katına çıkanlar.",
        "technical",
        scan_volume_shock,
    ),
    ScanDefinition(
        "zirve_52h",
        "52 Hafta Zirvesi",
        "Kapanışı önceki 252 günün en yükseğini geçenler.",
        "technical",
        scan_52w_high,
    ),
    ScanDefinition(
        "bb_sikisma",
        "Bollinger Sıkışması",
        "Bollinger bant genişliği son 120 günün en dar %10'unda olanlar.",
        "technical",
        scan_bollinger_squeeze,
    ),
    ScanDefinition(
        "ucuz_karli",
        "Ucuz ve Kârlı",
        "Yayımlanmış son yıl kârı pozitif ve F/K 10 veya altında.",
        "fundamental",
        scan_cheap_profitable,
    ),
    ScanDefinition(
        "satis_buyume",
        "Satış Büyümesi",
        "Son yayımlanmış çeyrekte satışlar yıllık en az %20 artmış.",
        "fundamental",
        scan_sales_growth,
    ),
    ScanDefinition(
        "temettu_verimi",
        "Temettü Verimi",
        "Son 12 ay brüt nakit temettü verimi en az %4 olanlar.",
        "temettu",
        scan_dividend_yield,
    ),
)

SCANS_BY_CODE: dict[str, ScanDefinition] = {scan.code: scan for scan in SCANS}


def bars_until(bars: Sequence[DailyBar], as_of: date) -> list[DailyBar]:
    """Defensive slice: never let a scan see a bar after ``as_of``."""
    return [bar for bar in bars if bar.date <= as_of]


__all__ = [
    "MIN_BARS",
    "SCANS",
    "SCANS_BY_CODE",
    "FundamentalContext",
    "ScanDefinition",
    "ScanHit",
    "bars_until",
    "scan_52w_high",
    "scan_bollinger_squeeze",
    "scan_cheap_profitable",
    "scan_dividend_yield",
    "scan_rsi_dip",
    "scan_sales_growth",
    "scan_sma_5_22",
    "scan_sma_50_200",
    "scan_volume_shock",
]
