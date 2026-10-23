"""Faz 8a: does a screen actually work?

For every screen hit we measure the forward return and compare it with XU100
and with a fixed random basket of symbols. The point is to publish an honest
score, including the cases where a screen loses to the market.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.market_data_repository import DailyBar, MarketDataRepository
from bist_bot.strategy.scans import SCANS, SCANS_BY_CODE

HORIZONS = (5, 20, 60)
RANDOM_BASKET = 20
MIN_OBSERVATIONS = 30


@dataclass
class HorizonScore:
    horizon: int
    observations: int
    scan_mean_pct: float | None
    xu100_mean_pct: float | None
    random_mean_pct: float | None
    excess_vs_xu100_pct: float | None
    excess_vs_random_pct: float | None
    t_stat: float | None
    win_rate_pct: float | None
    reliable: bool


@dataclass
class ScanScore:
    scan_id: str
    title: str
    first_date: date | None
    last_date: date | None
    horizons: list[HorizonScore] = field(default_factory=list)
    note: str | None = None


def _forward_returns(series: list[DailyBar], horizon: int) -> dict[date, float]:
    """Return map: date -> forward return over ``horizon`` bars."""
    out: dict[date, float] = {}
    for index, bar in enumerate(series):
        target = index + horizon
        if target >= len(series):
            break
        base = bar.close
        if base <= 0:
            continue
        out[bar.date] = series[target].close / base - 1.0
    return out


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values) * 100.0, 2) if values else None


def _t_stat(differences: list[float]) -> float | None:
    if len(differences) < 3:
        return None
    stdev = statistics.stdev(differences)
    if stdev == 0:
        return None
    return round(statistics.fmean(differences) / (stdev / len(differences) ** 0.5), 2)


class ScanScorecardService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings

    # ------------------------------------------------------------------
    def _random_basket(self, scan_id: str, first_date: date) -> list[str]:
        instruments = self.repository.list_active_instruments()
        tickers = sorted(item.ticker for item in instruments)
        if not tickers:
            return []
        rng = random.Random(f"{scan_id}:{first_date.isoformat()}")
        return rng.sample(tickers, min(RANDOM_BASKET, len(tickers)))

    def scorecard(
        self,
        scan_id: str,
        *,
        since: date | None = None,
        horizons: tuple[int, ...] = HORIZONS,
    ) -> dict[str, Any] | None:
        scan = SCANS_BY_CODE.get(scan_id)
        if scan is None:
            return None
        hits = self.repository.get_scan_results_range(scan_id, start=since or date(2016, 1, 1))
        if not hits:
            return {
                "scan_id": scan_id,
                "title": scan.title,
                "first_date": None,
                "last_date": None,
                "horizons": [],
                "note": "Bu tarama için kayıtlı sonuç yok.",
            }

        first_date = min(row["as_of"] for row in hits)
        last_date = max(row["as_of"] for row in hits)
        hit_tickers = {str(row["ticker"]) for row in hits}
        basket = self._random_basket(scan_id, first_date)
        tickers = sorted(hit_tickers | set(basket))
        start = first_date - timedelta(days=10)
        bars = self.repository.get_bars_for_tickers(tickers, start=start)
        xu_bars = dict(self.repository.get_benchmark_bars("XU100", start=start))
        xu_series = [DailyBar(date=d, close=v) for d, v in sorted(xu_bars.items())]

        by_horizon: list[HorizonScore] = []
        for horizon in horizons:
            forward = {ticker: _forward_returns(series, horizon) for ticker, series in bars.items()}
            xu_map = _forward_returns(xu_series, horizon)
            scan_returns: list[float] = []
            excess: list[float] = []
            random_returns: list[float] = []
            for row in hits:
                hit_date = row["as_of"]
                ticker = str(row["ticker"])
                value = forward.get(ticker, {}).get(hit_date)
                if value is None:
                    continue
                scan_returns.append(value)
                benchmark = xu_map.get(hit_date)
                if benchmark is not None:
                    excess.append(value - benchmark)
                day_random = [
                    forward[symbol][hit_date]
                    for symbol in basket
                    if hit_date in forward.get(symbol, {})
                ]
                if day_random:
                    random_returns.append(statistics.fmean(day_random))

            xu_values = [xu_map[row["as_of"]] for row in hits if row["as_of"] in xu_map]
            scan_mean = _mean(scan_returns)
            xu_mean = _mean(xu_values)
            random_mean = _mean(random_returns)
            n = len(scan_returns)
            by_horizon.append(
                HorizonScore(
                    horizon=horizon,
                    observations=n,
                    scan_mean_pct=scan_mean,
                    xu100_mean_pct=xu_mean,
                    random_mean_pct=random_mean,
                    excess_vs_xu100_pct=(
                        round(scan_mean - xu_mean, 2)
                        if scan_mean is not None and xu_mean is not None
                        else None
                    ),
                    excess_vs_random_pct=(
                        round(scan_mean - random_mean, 2)
                        if scan_mean is not None and random_mean is not None
                        else None
                    ),
                    t_stat=_t_stat(excess),
                    win_rate_pct=_mean([1.0 if value > 0 else 0.0 for value in scan_returns]),
                    reliable=(
                        n >= MIN_OBSERVATIONS
                        and (t := _t_stat(excess)) is not None
                        and abs(t) >= 2.0
                    ),
                )
            )

        return {
            "scan_id": scan_id,
            "title": scan.title,
            "first_date": first_date.isoformat(),
            "last_date": last_date.isoformat(),
            "horizons": [score.__dict__ for score in by_horizon],
            "note": (
                "XU100 ve rastgele sepet aynı günlerde, aynı ufukta ölçülür. "
                "30 gözlemden az veya |t| < 2 olan satırlar kanıt sayılmaz."
            ),
        }

    def all_scorecards(
        self, *, since: date | None = None, horizons: tuple[int, ...] = HORIZONS
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for scan in SCANS:
            payload = self.scorecard(scan.code, since=since, horizons=horizons)
            if payload is not None:
                out.append(payload)
        return out


__all__ = [
    "HORIZONS",
    "MIN_OBSERVATIONS",
    "HorizonScore",
    "ScanScore",
    "ScanScorecardService",
]
