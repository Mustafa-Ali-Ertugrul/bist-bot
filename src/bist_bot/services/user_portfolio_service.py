"""Faz 5: watchlist views and the manual portfolio with cash-flow-matched benchmarks.

Share counts are stored in "adjusted units" so bonus issues and splits never
show a fake loss: units = qty * raw_price / adjusted_price at the trade date.
"""

from __future__ import annotations

import csv
import io
import math
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.market_data_repository import MarketDataRepository
from bist_bot.db.repositories.user_portfolio_repository import (
    DuplicateError,
    OwnershipError,
    UserPortfolioRepository,
)

XU100 = "XU100"
MMF = "MMF"
VALID_SIDES = ("buy", "sell")


@dataclass(frozen=True)
class PricePoint:
    raw: float
    adjusted: float


class TradeError(ValueError):
    """Invalid trade input (API renders 400)."""


def _pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator - 1.0) * 100.0, 2)


_LEDGER_LOCKS: dict[tuple[int, int], threading.Lock] = {}
_LEDGER_LOCKS_GUARD = threading.Lock()


def _ledger_lock(user_id: int, portfolio_id: int) -> threading.Lock:
    """Per-portfolio lock serializing ledger check-then-act mutations."""
    key = (int(user_id), int(portfolio_id))
    with _LEDGER_LOCKS_GUARD:
        lock = _LEDGER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LEDGER_LOCKS[key] = lock
        return lock


class UserPortfolioService:
    def __init__(
        self,
        user_repository: UserPortfolioRepository,
        market_repository: MarketDataRepository,
        settings: Any | None = None,
    ) -> None:
        self.user_repository = user_repository
        self.market_repository = market_repository
        self.settings = settings or default_settings

    # ------------------------------------------------------------------
    # Watchlist view
    # ------------------------------------------------------------------
    def watchlists(self, user_id: int) -> list[dict[str, Any]]:
        lists = self.user_repository.list_watchlists(user_id)
        snapshots = {row["ticker"]: row for row in self.market_repository.get_snapshots()}
        instruments = {item.ticker: item for item in self.market_repository.list_instruments()}
        for group in lists:
            rows: list[dict[str, Any]] = []
            for ticker in group["tickers"]:
                instrument = instruments.get(ticker)
                snapshot = snapshots.get(ticker, {})
                rows.append(
                    {
                        "code": instrument.code if instrument else ticker.removesuffix(".IS"),
                        "name": instrument.name if instrument else "",
                        "sector": instrument.sector if instrument else None,
                        "close": snapshot.get("close"),
                        "change_pct": snapshot.get("change_pct"),
                        "ret_1m": snapshot.get("ret_1m"),
                        "rsi14": snapshot.get("rsi14"),
                        "pe_ttm": snapshot.get("pe_ttm"),
                        "as_of": snapshot.get("as_of"),
                    }
                )
            group["rows"] = rows
        return lists

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------
    def summary(self, user_id: int, portfolio_id: int) -> dict[str, Any]:
        transactions = self.user_repository.get_transactions(user_id, portfolio_id)
        if not transactions:
            return {
                "transactions": [],
                "positions": [],
                "closed_positions": [],
                "totals": {},
                "benchmark": {},
                "series": [],
            }

        tickers = sorted({tx["ticker"] for tx in transactions})
        start = min(tx["trade_date"] for tx in transactions)
        prices = {ticker: self._prices(ticker, start) for ticker in tickers}

        holdings: dict[str, dict[str, float]] = {}
        cash = 0.0
        realized = 0.0
        total_bought = 0.0
        total_sold = 0.0
        net_invested = 0.0
        for tx in transactions:
            ticker = tx["ticker"]
            point = self._price_on(prices[ticker], tx["trade_date"])
            if point is None:
                raise TradeError(f"{ticker} için {tx['trade_date']} civarında fiyat yok.")
            units = tx["quantity"] * point.raw / point.adjusted
            gross = tx["quantity"] * tx["price"]
            if tx["side"] == "buy":
                # A buy draws down portfolio cash first; only the remainder is
                # fresh money from outside (net_invested).
                total_bought += gross
                outflow = gross + tx["commission_tl"]
                used = max(0.0, min(cash, outflow))
                cash -= used
                net_invested += outflow - used
                state = holdings.setdefault(
                    ticker, {"units": 0.0, "cost": 0.0, "realized": 0.0}
                )
                state["units"] += units
                state["cost"] += outflow
            else:
                state = holdings.setdefault(
                    ticker, {"units": 0.0, "cost": 0.0, "realized": 0.0}
                )
                if units > state["units"] + 1e-9:
                    raise TradeError(f"{ticker} için elde olandan fazla satış.")
                average = state["cost"] / state["units"] if state["units"] else 0.0
                removed_cost = average * units
                state["units"] -= units
                state["cost"] -= removed_cost
                # Sale proceeds stay inside the portfolio as cash.
                proceeds = gross - tx["commission_tl"]
                cash += proceeds
                total_sold += gross
                tx_realized = proceeds - removed_cost
                realized += tx_realized
                state["realized"] += tx_realized

        instruments = {item.ticker: item for item in self.market_repository.list_instruments()}
        positions: list[dict[str, Any]] = []
        closed_positions: list[dict[str, Any]] = []
        market_value = 0.0
        remaining_cost = 0.0
        for ticker, state in holdings.items():
            instrument = instruments.get(ticker)
            if state["units"] <= 1e-9:
                closed_positions.append(
                    {
                        "code": instrument.code if instrument else ticker.removesuffix(".IS"),
                        "name": instrument.name if instrument else "",
                        "realized_pnl": round(state["realized"], 2),
                    }
                )
                continue
            bars = prices[ticker]
            latest_date, latest = bars[-1]
            value = state["units"] * latest.adjusted
            cost = state["cost"]
            market_value += value
            remaining_cost += cost
            positions.append(
                {
                    "code": instrument.code if instrument else ticker.removesuffix(".IS"),
                    "name": instrument.name if instrument else "",
                    "quantity": round(state["units"] * latest.raw / latest.adjusted, 4),
                    "avg_cost": round(cost / state["units"] * latest.adjusted / latest.raw, 4)
                    if state["units"]
                    else None,
                    "price": round(latest.raw, 4),
                    "value": round(value, 2),
                    "cost_basis": round(cost, 2),
                    "unrealized": round(value - cost, 2),
                    "unrealized_pct": _pct(value, cost),
                    "realized_pnl": round(state["realized"], 2),
                    "weight_pct": None,
                }
            )
        total_value = market_value + cash
        for position in positions:
            position["weight_pct"] = (
                round(position["value"] / total_value * 100.0, 2) if total_value else None
            )

        benchmark = self._benchmark_curves(transactions, prices, start)
        totals = {
            "value": round(total_value, 2),
            "cash": round(cash, 2),
            "invested_cost": round(remaining_cost, 2),
            "unrealized": round(market_value - remaining_cost, 2),
            "realized": round(realized, 2),
            "total_bought": round(total_bought, 2),
            "total_sold": round(total_sold, 2),
            "net_invested": round(net_invested, 2),
            "return_pct": _pct(total_value, net_invested) if net_invested else None,
        }
        return {
            "transactions": [
                {**tx, "trade_date": tx["trade_date"].isoformat()} for tx in transactions
            ],
            "positions": sorted(positions, key=lambda row: row["value"], reverse=True),
            "closed_positions": closed_positions,
            "totals": totals,
            "benchmark": benchmark["summary"],
            "series": benchmark["series"],
        }

    # ------------------------------------------------------------------
    # Trade validation + persistence
    # ------------------------------------------------------------------
    def _parse_transaction_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticker_input = str(payload.get("ticker") or "").strip().upper()
        code = ticker_input.removesuffix(".IS")
        instrument = self.market_repository.get_instrument(code)
        if instrument is None:
            raise TradeError("Hisse bulunamadı.")
        raw_side = str(payload.get("side") or "").strip().lower()
        if raw_side in ("alış", "alis", "al", "b"):
            side = "buy"
        elif raw_side in ("satış", "satis", "sat", "s"):
            side = "sell"
        else:
            side = raw_side
        if side not in VALID_SIDES:
            raise TradeError("Yön alış veya satış olmalı.")
        try:
            trade_date = date.fromisoformat(str(payload.get("trade_date") or "").strip())
        except ValueError as exc:
            raise TradeError("Tarih YYYY-AA-GG olmalı.") from exc
        configured_start = str(getattr(self.settings, "DAILY_BARS_START_DATE", "2016-01-01"))
        try:
            earliest = date.fromisoformat(configured_start)
        except ValueError:
            earliest = date(2016, 1, 1)
        if trade_date > date.today():
            raise TradeError("Gelecek tarihli işlem girilemez.")
        if trade_date < earliest:
            raise TradeError(f"Veri {earliest.isoformat()} tarihinden başlıyor.")
        try:
            quantity = float(payload.get("quantity"))
            price = float(payload.get("price"))
            commission_raw = payload.get("commission_tl")
            if commission_raw in (None, ""):
                commission_raw = payload.get("commission")
            commission = float(commission_raw or 0.0)
        except (TypeError, ValueError) as exc:
            raise TradeError("Adet, fiyat ve komisyon sayı olmalı.") from exc
        for value in (quantity, price, commission):
            if not math.isfinite(value):
                raise TradeError("Adet, fiyat ve komisyon geçerli sayı olmalı.")
        if quantity <= 0 or price <= 0:
            raise TradeError("Adet ve fiyat sıfırdan büyük olmalı.")
        if commission < 0:
            raise TradeError("Komisyon negatif olamaz.")
        return {
            "ticker": instrument.ticker,
            "side": side,
            "trade_date": trade_date,
            "quantity": quantity,
            "price": price,
            "commission_tl": commission,
            "note": payload.get("note"),
        }

    def add_transaction(
        self,
        user_id: int,
        portfolio_id: int,
        payload: dict[str, Any],
        *,
        limit: int = 500,
    ) -> int:
        with _ledger_lock(user_id, portfolio_id):
            return self._add_transaction_unlocked(
                user_id, portfolio_id, payload, limit=limit
            )

    def _add_transaction_unlocked(
        self,
        user_id: int,
        portfolio_id: int,
        payload: dict[str, Any],
        *,
        limit: int = 500,
    ) -> int:
        record = self._parse_transaction_payload(payload)
        if record["side"] == "sell":
            held = self._held_units(
                user_id, portfolio_id, record["ticker"], record["trade_date"]
            )
            point = self._price_on(
                self._prices(record["ticker"], record["trade_date"]), record["trade_date"]
            )
            if point is None:
                raise TradeError("Satış tarihinde fiyat verisi yok.")
            units = record["quantity"] * point.raw / point.adjusted
            if units > held + 1e-9:
                raise TradeError("Elde olandan fazla satış girilemez.")

        existing = self.user_repository.get_transactions(user_id, portfolio_id)
        self._validate_ledger([*existing, record])
        return self.user_repository.add_transaction(user_id, portfolio_id, record, limit=limit)

    def update_transaction(
        self,
        user_id: int,
        portfolio_id: int,
        transaction_id: int,
        payload: dict[str, Any],
    ) -> None:
        with _ledger_lock(user_id, portfolio_id):
            self._update_transaction_unlocked(
                user_id, portfolio_id, transaction_id, payload
            )

    def _update_transaction_unlocked(
        self,
        user_id: int,
        portfolio_id: int,
        transaction_id: int,
        payload: dict[str, Any],
    ) -> None:
        record = self._parse_transaction_payload(payload)
        existing = self.user_repository.get_transactions(user_id, portfolio_id)
        updated: list[dict[str, Any]] = []
        found = False
        for tx in existing:
            if int(tx["id"]) == int(transaction_id):
                found = True
                updated.append({**record, "id": tx["id"]})
            else:
                updated.append(tx)
        if not found:
            raise OwnershipError("İşlem bulunamadı.")
        self._validate_ledger(updated)
        self.user_repository.update_transaction(user_id, portfolio_id, transaction_id, record)

    def import_transactions_csv(
        self,
        user_id: int,
        portfolio_id: int,
        csv_text: str,
        *,
        dry_run: bool = False,
        limit: int = 500,
    ) -> dict[str, Any]:
        existing = self.user_repository.get_transactions(user_id, portfolio_id)
        cleaned = (csv_text or "").lstrip("\ufeff").strip()
        if not cleaned:
            raise TradeError("CSV içeriği boş olamaz.")
        first_line = cleaned.splitlines()[0]
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.reader(io.StringIO(cleaned), delimiter=delimiter)
        raw_rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not raw_rows:
            raise TradeError("CSV içeriği boş olamaz.")

        header_aliases = {
            "trade_date": "trade_date",
            "date": "trade_date",
            "tarih": "trade_date",
            "ticker": "ticker",
            "code": "ticker",
            "kod": "ticker",
            "hisse": "ticker",
            "side": "side",
            "yon": "side",
            "yön": "side",
            "quantity": "quantity",
            "qty": "quantity",
            "adet": "quantity",
            "price": "price",
            "fiyat": "price",
            "commission": "commission_tl",
            "commission_tl": "commission_tl",
            "komisyon": "commission_tl",
            "note": "note",
            "not": "note",
        }
        first_norm = [cell.strip().lower() for cell in raw_rows[0]]
        has_header = any(col in header_aliases for col in first_norm)
        if has_header:
            col_map = [header_aliases.get(col) for col in first_norm]
            data_rows = list(enumerate(raw_rows[1:], start=2))
        else:
            default_cols = [
                "trade_date",
                "ticker",
                "side",
                "quantity",
                "price",
                "commission_tl",
                "note",
            ]
            col_map = default_cols[: len(raw_rows[0])]
            data_rows = list(enumerate(raw_rows, start=1))

        if not data_rows:
            raise TradeError("CSV içinde eklenecek işlem satırı yok.")
        if len(existing) + len(data_rows) > limit:
            raise TradeError(f"Bir portföyde en fazla {limit} işlem olabilir.")

        parsed: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for line_no, cells in data_rows:
            row_dict: dict[str, Any] = {}
            for idx, key in enumerate(col_map):
                if key and idx < len(cells):
                    row_dict[key] = cells[idx].strip()
            try:
                parsed.append(self._parse_transaction_payload(row_dict))
            except TradeError as exc:
                errors.append({"row": line_no, "message": str(exc)})

        if not errors and parsed:
            try:
                self._validate_ledger([*existing, *parsed])
            except TradeError as exc:
                errors.append({"row": 0, "message": str(exc)})

        if errors:
            return {
                "valid": False,
                "dry_run": dry_run,
                "imported": 0,
                "preview_count": len(parsed),
                "errors": errors,
            }

        imported = 0
        if not dry_run:
            imported = self.user_repository.add_transactions_bulk(
                user_id, portfolio_id, parsed, limit=limit
            )
        return {
            "valid": True,
            "dry_run": dry_run,
            "imported": imported,
            "preview_count": len(parsed),
            "errors": [],
        }

    def delete_transaction(self, user_id: int, portfolio_id: int, transaction_id: int) -> None:
        existing = self.user_repository.get_transactions(user_id, portfolio_id)
        remaining = [tx for tx in existing if int(tx["id"]) != int(transaction_id)]
        if len(remaining) == len(existing):
            raise OwnershipError("İşlem bulunamadı.")
        self._validate_ledger(remaining)
        self.user_repository.delete_transaction(user_id, portfolio_id, transaction_id)

    def _validate_ledger(self, transactions: list[dict[str, Any]]) -> None:
        """Replay the ledger in trade order; no point in time may oversell.

        Checking only up to the inserted/deleted transaction misses back-dated
        entries, which leave later sells over-owning and break summary().
        """
        if not transactions:
            return
        starts: dict[str, date] = {}
        for tx in transactions:
            current = starts.get(tx["ticker"])
            if current is None or tx["trade_date"] < current:
                starts[tx["ticker"]] = tx["trade_date"]
        prices = {ticker: self._prices(ticker, start) for ticker, start in starts.items()}
        held: dict[str, float] = {}
        ordered = sorted(
            transactions,
            key=lambda item: (item["trade_date"], 0 if item["side"] == "buy" else 1),
        )
        for tx in ordered:
            ticker = tx["ticker"]
            point = self._price_on(prices[ticker], tx["trade_date"])
            if point is None:
                raise TradeError(f"{ticker} için {tx['trade_date']} civarında fiyat yok.")
            units = tx["quantity"] * point.raw / point.adjusted
            balance = held.get(ticker, 0.0) + (units if tx["side"] == "buy" else -units)
            if balance < -1e-9:
                raise TradeError(f"{ticker} için elde olandan fazla satış.")
            held[ticker] = balance

    def _held_units(self, user_id: int, portfolio_id: int, ticker: str, until: date) -> float:
        transactions = [
            tx
            for tx in self.user_repository.get_transactions(user_id, portfolio_id)
            if tx["ticker"] == ticker and tx["trade_date"] <= until
        ]
        if not transactions:
            return 0.0
        prices = self._prices(ticker, min(tx["trade_date"] for tx in transactions))
        held = 0.0
        for tx in transactions:
            point = self._price_on(prices, tx["trade_date"])
            if point is None:
                continue
            units = tx["quantity"] * point.raw / point.adjusted
            held += units if tx["side"] == "buy" else -units
        return held

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------
    def _prices(self, ticker: str, start: date) -> list[tuple[date, PricePoint]]:
        bars = self.market_repository.get_bars(ticker, start=start - timedelta(days=10))
        points: list[tuple[date, PricePoint]] = []
        for bar in bars:
            raw = bar.close_raw or bar.close
            points.append((bar.date, PricePoint(raw=raw, adjusted=bar.close)))
        if points:
            return points
        all_bars = self.market_repository.get_bars(ticker, limit=1)
        if all_bars:
            bar = all_bars[-1]
            return [(bar.date, PricePoint(raw=bar.close_raw or bar.close, adjusted=bar.close))]
        return []

    @staticmethod
    def _price_on(points: list[tuple[date, PricePoint]], target: date) -> PricePoint | None:
        chosen: PricePoint | None = None
        for bar_date, point in points:
            if bar_date <= target:
                chosen = point
            else:
                break
        return chosen

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------
    def _benchmark_curves(
        self,
        transactions: list[dict[str, Any]],
        prices: dict[str, list[tuple[date, PricePoint]]],
        start: date,
    ) -> dict[str, Any]:
        xu = dict(
            self.market_repository.get_benchmark_bars(XU100, start=start - timedelta(days=10))
        )
        if not xu:
            return {"summary": {"available": False}, "series": []}

        rate_pct = float(getattr(self.settings, "MONEY_MARKET_ANNUAL_RATE_PCT", 0.0))
        mm_source = "assumption"
        mm_bars = dict(
            self.market_repository.get_benchmark_bars(MMF, start=start - timedelta(days=10))
        )
        if mm_bars:
            mm_source = "tefas"
        elif rate_pct <= 0:
            mm_source = "unset"

        first_xu_date = min(xu)
        mm_base = mm_bars[min(mm_bars)] if mm_bars else 1.0

        def mm_on(day: date) -> float:
            if mm_bars:
                chosen = None
                for bar_date, value in mm_bars.items():
                    if bar_date <= day:
                        chosen = value
                return chosen if chosen is not None else mm_base
            days = max(0, (day - first_xu_date).days)
            return mm_base * (1.0 + rate_pct / 100.0) ** (days / 365.0)

        def xu_on(day: date) -> float | None:
            chosen = None
            for bar_date, value in xu.items():
                if bar_date <= day:
                    chosen = value
            return chosen

        cash = 0.0
        xu_units = 0.0
        mm_units = 0.0
        grouped: dict[date, list[dict[str, Any]]] = {}
        for tx in transactions:
            grouped.setdefault(tx["trade_date"], []).append(tx)

        # Include every trade date so weekend/holiday trades are not dropped
        # just because the benchmark has no session that day.
        days = sorted({*[day for day in xu if day >= start], *grouped})
        series: list[dict[str, Any]] = []
        units_by_ticker: dict[str, float] = {}
        benchmark_complete = True
        for day in days:
            for tx in grouped.get(day, []):
                point = self._price_on(prices[tx["ticker"]], day)
                if point is None:
                    continue
                gross = tx["quantity"] * tx["price"]
                if tx["side"] == "buy":
                    outflow = gross + tx["commission_tl"]
                    used = max(0.0, min(cash, outflow))
                    cash -= used
                    # Benchmarks track the same outside money only; internal
                    # cash (sale proceeds) never adds benchmark units.
                    external = outflow - used
                    if external > 0:
                        day_xu = xu_on(day)
                        if day_xu is None:
                            benchmark_complete = False
                        else:
                            xu_units += external / day_xu
                        mm_day = mm_on(day)
                        if mm_day:
                            mm_units += external / mm_day
                else:
                    # Sale proceeds stay in the portfolio as cash.
                    cash += gross - tx["commission_tl"]
                units_delta = tx["quantity"] * point.raw / point.adjusted
                units_by_ticker[tx["ticker"]] = units_by_ticker.get(tx["ticker"], 0.0) + (
                    units_delta if tx["side"] == "buy" else -units_delta
                )

            portfolio_value = cash
            for ticker, units in units_by_ticker.items():
                if not units:
                    continue
                point = self._price_on(prices[ticker], day)
                if point is not None:
                    portfolio_value += units * point.adjusted
            day_xu = xu_on(day)
            series.append(
                {
                    "time": day.isoformat(),
                    "portfolio": round(portfolio_value, 2),
                    "xu100": round(xu_units * day_xu, 2) if day_xu else None,
                    "money_market": round(mm_units * mm_on(day), 2),
                }
            )

        if not benchmark_complete:
            return {"summary": {"available": False}, "series": []}

        portfolio_now = series[-1]["portfolio"] if series else 0.0
        xu_now = series[-1]["xu100"] if series else 0.0
        mm_now = series[-1]["money_market"] if series else 0.0
        summary = {
            "available": True,
            "as_of": series[-1]["time"] if series else None,
            "portfolio_value": portfolio_now,
            "xu100_value": xu_now,
            "money_market_value": mm_now,
            "vs_xu100": _pct(portfolio_now, xu_now) if xu_now else None,
            "vs_money_market": _pct(portfolio_now, mm_now) if mm_now else None,
            "money_market_source": mm_source,
            "money_market_rate_pct": rate_pct if mm_source == "assumption" else None,
        }
        # Keep the payload bounded; weekly samples for long histories.
        if len(series) > 700:
            step = max(1, len(series) // 700)
            series = [*series[::step], series[-1]]
        return {"summary": summary, "series": series}


__all__ = [
    "XU100",
    "DuplicateError",
    "OwnershipError",
    "TradeError",
    "UserPortfolioService",
]
