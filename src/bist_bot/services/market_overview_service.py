"""Faz P3.1: market overview for the product home page.

Everything here is descriptive: breadth counts, leader boards, sector
averages and the day's screen hit counts. No recommendation, no target and
no expected return is produced.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.market_data_repository import MarketDataRepository
from bist_bot.strategy.scans import SCANS

BENCHMARK_CODE = "XU100"
LEADER_LIMIT = 10


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


class MarketOverviewService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings

    def overview(self, *, as_of: date | None = None, limit: int = LEADER_LIMIT) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        target = as_of or self._latest_snapshot_date()
        if target is None:
            return {
                "as_of": None,
                "index": None,
                "breadth": {
                    "total": 0,
                    "advancers": 0,
                    "decliners": 0,
                    "unchanged": 0,
                    "advancer_pct": None,
                },
                "leaders": {"gainers": [], "losers": [], "volume": []},
                "sectors": [],
                "scans": [],
            }

        rows = self._snapshot_rows(target)
        breadth = self._breadth(rows)
        return {
            "as_of": target.isoformat(),
            "index": self._index(target),
            "breadth": breadth,
            "leaders": {
                "gainers": self._top(rows, "change_pct", limit, reverse=True),
                "losers": self._top(rows, "change_pct", limit, reverse=False),
                "volume": self._top(rows, "avg_volume_20", limit, reverse=True),
            },
            "sectors": self._sectors(rows),
            "scans": self._scans(target),
        }

    # ------------------------------------------------------------------
    def _latest_snapshot_date(self) -> date | None:
        rows = self.repository.list_snapshot_dates(limit=1)
        return date.fromisoformat(str(rows[0]["as_of"])) if rows else None

    def _snapshot_rows(self, target: date) -> list[dict[str, Any]]:
        instruments = {item.ticker: item for item in self.repository.list_instruments()}
        out: list[dict[str, Any]] = []
        for row in self.repository.get_snapshots(target):
            instrument = instruments.get(str(row["ticker"]))
            out.append(
                {
                    "code": instrument.code if instrument else str(row["ticker"]).removesuffix(".IS"),
                    "name": instrument.name if instrument else "",
                    "sector": (instrument.sector if instrument else None) or "",
                    "close": row.get("close"),
                    "change_pct": row.get("change_pct"),
                    "ret_1m": row.get("ret_1m"),
                    "market_cap_tl": row.get("market_cap_tl"),
                    "avg_volume_20": row.get("avg_volume_20"),
                }
            )
        return out

    @staticmethod
    def _breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
        advancers = decliners = unchanged = 0
        for row in rows:
            change = row.get("change_pct")
            if change is None:
                continue
            if change > 0:
                advancers += 1
            elif change < 0:
                decliners += 1
            else:
                unchanged += 1
        total = advancers + decliners + unchanged
        return {
            "total": total,
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
            "advancer_pct": _round(advancers / total * 100.0 if total else None, 1),
        }

    @staticmethod
    def _top(
        rows: list[dict[str, Any]], key: str, limit: int, *, reverse: bool
    ) -> list[dict[str, Any]]:
        usable = [row for row in rows if row.get(key) is not None]
        ordered = sorted(usable, key=lambda row: row[key], reverse=reverse)[:limit]
        return [
            {
                "code": row["code"],
                "name": row["name"],
                "sector": row["sector"] or None,
                "close": _round(row.get("close"), 2),
                "change_pct": _round(row.get("change_pct"), 2),
                "market_cap_tl": _round(row.get("market_cap_tl"), 0),
                "avg_volume_20": _round(row.get("avg_volume_20"), 0),
            }
            for row in ordered
        ]

    @staticmethod
    def _sectors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            sector = (row.get("sector") or "").strip()
            if not sector:
                continue
            grouped.setdefault(sector, []).append(row)

        out: list[dict[str, Any]] = []
        for sector, members in grouped.items():
            changes = [float(r["change_pct"]) for r in members if r.get("change_pct") is not None]
            monthly = [float(r["ret_1m"]) for r in members if r.get("ret_1m") is not None]
            out.append(
                {
                    "sector": sector,
                    "count": len(members),
                    "avg_change_pct": _round(_mean(changes)),
                    "median_change_pct": _round(_median(changes)),
                    "avg_ret_1m_pct": _round(_mean(monthly)),
                }
            )
        out.sort(
            key=lambda item: item["avg_change_pct"] if item["avg_change_pct"] is not None else -999.0,
            reverse=True,
        )
        return out

    def _index(self, target: date | None = None) -> dict[str, Any] | None:
        bars = self.repository.get_benchmark_bars(BENCHMARK_CODE)
        if target is not None:
            # A historical overview must show that day's index, not today's.
            bars = [bar for bar in bars if bar[0] <= target]
        if not bars:
            return None
        last_date, last_value = bars[-1]
        previous = bars[-2][1] if len(bars) > 1 else None
        change_pct = (
            (float(last_value) / float(previous) - 1.0) * 100.0
            if previous not in (None, 0)
            else None
        )
        return {
            "code": BENCHMARK_CODE,
            "as_of": last_date.isoformat(),
            "close": _round(last_value),
            "change_pct": _round(change_pct),
        }

    def _scans(self, target: date) -> list[dict[str, Any]]:
        counts = self.repository.count_scan_results(target)
        return [
            {
                "code": scan.code,
                "title": scan.title,
                "kind": scan.kind,
                "count": int(counts.get(scan.code, 0)),
            }
            for scan in SCANS
        ]
