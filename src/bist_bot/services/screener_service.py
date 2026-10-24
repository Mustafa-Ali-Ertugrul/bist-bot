"""Faz 4: ready-made screens and the custom filter engine.

Filters run in Python over one day's snapshot rows (max ~700), which keeps the
query surface free of any user-supplied SQL. The API layer decides how many
rows a caller may see; this service only paginates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.market_data_repository import MarketDataRepository
from bist_bot.strategy.scans import SCANS, SCANS_BY_CODE

OPERATORS = (">", ">=", "<", "<=", "between")
MAX_CONDITIONS = 10
DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class Field:
    code: str
    label: str
    unit: str  # "pct" | "tl" | "x" | ""


FIELDS: tuple[Field, ...] = (
    Field("close", "Kapanış", "tl"),
    Field("change_pct", "Günlük değişim", "pct"),
    Field("ret_1m", "1 ay getiri", "pct"),
    Field("ret_3m", "3 ay getiri", "pct"),
    Field("ret_1y", "1 yıl getiri", "pct"),
    Field("rsi14", "RSI(14)", ""),
    Field("sma50_gap_pct", "SMA50'ye uzaklık", "pct"),
    Field("sma200_gap_pct", "SMA200'e uzaklık", "pct"),
    Field("from_52w_high_pct", "52 hafta zirvesine uzaklık", "pct"),
    Field("avg_volume_20", "20g ortalama hacim", "tl"),
    Field("market_cap_tl", "Piyasa değeri", "tl"),
    Field("pe_ttm", "F/K (son 12 ay)", "x"),
    Field("pb", "PD/DD", "x"),
    Field("net_margin_pct", "Net kâr marjı", "pct"),
    Field("roe_pct", "Özkaynak kârlılığı", "pct"),
    Field("sales_growth_yoy_pct", "Satış büyümesi (yıllık)", "pct"),
    Field("dividend_yield_pct", "Temettü verimi (12 ay)", "pct"),
)
FIELDS_BY_CODE = {field.code: field for field in FIELDS}
SORTABLE = tuple(field.code for field in FIELDS)


class ScreenerError(ValueError):
    """Invalid user input (API renders this as 400)."""


def _number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScreenerError(f"{name} sayı olmalı.") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ScreenerError(f"{name} geçerli bir sayı olmalı.")
    return number


def parse_conditions(raw: Any) -> list[dict[str, Any]]:
    """Validate a user condition list; unknown fields/operators are rejected."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ScreenerError("Koşullar liste olmalı.")
    if len(raw) > MAX_CONDITIONS:
        raise ScreenerError(f"En fazla {MAX_CONDITIONS} koşul eklenebilir.")
    conditions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ScreenerError("Koşul nesnesi geçersiz.")
        field = str(item.get("field") or "")
        if field not in FIELDS_BY_CODE:
            raise ScreenerError(f"Bilinmeyen alan: {field}")
        op = str(item.get("op") or "")
        if op not in OPERATORS:
            raise ScreenerError(f"Bilinmeyen operatör: {op}")
        if op == "between":
            low = _number(item.get("value"), "Alt sınır")
            high = _number(item.get("value2"), "Üst sınır")
            if low > high:
                low, high = high, low
            conditions.append({"field": field, "op": op, "value": low, "value2": high})
        else:
            conditions.append(
                {"field": field, "op": op, "value": _number(item.get("value"), "Değer")}
            )
    return conditions


def matches(row: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    for condition in conditions:
        value = row.get(condition["field"])
        if value is None:
            return False
        if condition["op"] == "between":
            if not (condition["value"] <= value <= condition["value2"]):
                return False
        elif condition["op"] == ">":
            if not value > condition["value"]:
                return False
        elif condition["op"] == ">=":
            if not value >= condition["value"]:
                return False
        elif condition["op"] == "<":
            if not value < condition["value"]:
                return False
        elif condition["op"] == "<=":
            if not value <= condition["value"]:
                return False
    return True


class ScreenerService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings

    # ------------------------------------------------------------------
    # Ready-made screens
    # ------------------------------------------------------------------
    def catalog(self, as_of: date | None = None) -> dict[str, Any]:
        dates = self.repository.list_scan_dates(limit=60)
        latest = as_of or (date.fromisoformat(dates[0]) if dates else None)
        counts = self.repository.count_scan_results(latest) if latest else {}
        return {
            "as_of": latest.isoformat() if latest else None,
            "dates": dates,
            "screens": [
                {
                    "code": scan.code,
                    "title": scan.title,
                    "description": scan.description,
                    "kind": scan.kind,
                    "count": counts.get(scan.code, 0),
                }
                for scan in SCANS
            ],
        }

    def screen_rows(
        self,
        scan_id: str,
        *,
        as_of: date | None = None,
        sort: str = "market_cap_tl",
        order: str = "desc",
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> dict[str, Any]:
        if scan_id not in SCANS_BY_CODE:
            raise ScreenerError("Bilinmeyen tarama.")
        target = as_of or self._latest_snapshot_date()
        if target is None:
            return {"as_of": None, "total": 0, "rows": []}
        hits = self.repository.get_scan_results(scan_id, target)
        if not hits:
            return {"as_of": target.isoformat(), "total": 0, "rows": []}
        by_ticker = {str(hit["ticker"]): hit for hit in hits}
        snapshots = [
            row for row in self.repository.get_snapshots(target) if row["ticker"] in by_ticker
        ]
        return self._render(
            snapshots,
            as_of=target,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
            extra={
                ticker: {
                    "scan_value": by_ticker[ticker]["value"],
                    "detail": by_ticker[ticker]["detail"],
                }
                for ticker in by_ticker
            },
        )

    # ------------------------------------------------------------------
    # Custom filter
    # ------------------------------------------------------------------
    def query(
        self,
        *,
        conditions: list[dict[str, Any]] | None = None,
        sector: str | None = None,
        scan_id: str | None = None,
        as_of: date | None = None,
        sort: str = "market_cap_tl",
        order: str = "desc",
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> dict[str, Any]:
        conditions = conditions or []
        target = as_of or self._latest_snapshot_date()
        if target is None:
            return {"as_of": None, "total": 0, "rows": []}
        rows = self.repository.get_snapshots(target)
        instruments = {item.ticker: item for item in self.repository.list_instruments()}
        if sector:
            sector_key = sector.strip().casefold()
            filtered: list[dict[str, Any]] = []
            for row in rows:
                instrument = instruments.get(str(row["ticker"]))
                value = (instrument.sector if instrument else None) or ""
                if value.casefold() == sector_key:
                    filtered.append(row)
            rows = filtered
        if scan_id:
            if scan_id not in SCANS_BY_CODE:
                raise ScreenerError("Bilinmeyen tarama.")
            members = {
                str(hit["ticker"]) for hit in self.repository.get_scan_results(scan_id, target)
            }
            rows = [row for row in rows if row["ticker"] in members]
        rows = [row for row in rows if matches(row, conditions)]
        return self._render(rows, as_of=target, sort=sort, order=order, limit=limit, offset=offset)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _latest_snapshot_date(self) -> date | None:
        rows = self.repository.list_snapshot_dates(limit=1)
        return date.fromisoformat(str(rows[0]["as_of"])) if rows else None

    def _render(
        self,
        rows: list[dict[str, Any]],
        *,
        as_of: date,
        sort: str,
        order: str,
        limit: int,
        offset: int,
        extra: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if sort not in SORTABLE:
            raise ScreenerError("Bu alana göre sıralanamaz.")
        reverse = (order or "desc").lower() != "asc"
        non_null = [row for row in rows if row.get(sort) is not None]
        nulls = [row for row in rows if row.get(sort) is None]
        ordered = sorted(non_null, key=lambda row: row.get(sort), reverse=reverse) + nulls
        page_size = max(1, min(int(limit), 200))
        start = max(0, int(offset))
        page = ordered[start : start + page_size]

        instruments = {item.ticker: item for item in self.repository.list_instruments()}
        out: list[dict[str, Any]] = []
        for row in page:
            instrument = instruments.get(str(row["ticker"]))
            item: dict[str, Any] = {
                "code": instrument.code if instrument else str(row["ticker"]).removesuffix(".IS"),
                "name": instrument.name if instrument else "",
                "sector": instrument.sector if instrument else None,
                "as_of": row["as_of"],
                "metrics": {field.code: row.get(field.code) for field in FIELDS},
            }
            if extra and str(row["ticker"]) in extra:
                item.update(extra[str(row["ticker"])])
            out.append(item)
        return {"as_of": as_of.isoformat(), "total": len(ordered), "rows": out}

    def sectors(self) -> list[str]:
        values = {
            (item.sector or "").strip()
            for item in self.repository.list_instruments()
            if (item.sector or "").strip()
        }
        return sorted(values)

    @staticmethod
    def field_list() -> list[dict[str, str]]:
        return [{"code": field.code, "label": field.label, "unit": field.unit} for field in FIELDS]
