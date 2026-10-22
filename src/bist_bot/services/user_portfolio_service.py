"""Faz 5: watchlist views and the manual portfolio with cash-flow-matched benchmarks.

Share counts are stored in "adjusted units" so bonus issues and splits never
show a fake loss: units = qty * raw_price / adjusted_price at the trade date.
"""

from __future__ import annotations

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
        for tx in transactions:
            ticker = tx["ticker"]
            point = self._price_on(prices[ticker], tx["trade_date"])
            if point is None:
                raise TradeError(f"{ticker} için {tx['trade_date']} civarında fiyat yok.")
            units = tx["quantity"] * point.raw / point.adjusted
            gross = tx["quantity"] * tx["price"]
            if tx["side"] == "buy":
                # Buys are funded from outside the portfolio; they are not cash out.
                total_bought += gross
                state = holdings.setdefault(ticker, {"units": 0.0, "cost": 0.0})
                state["units"] += units
                state["cost"] += gross + tx["commission_tl"]
            else:
                state = holdings.setdefault(ticker, {"units": 0.0, "cost": 0.0})
                if units > state["units"] + 1e-9:
                    raise TradeError(f"{ticker} için elde olandan fazla satış.")
                average = state["cost"] / state["units"] if state["units"] else 0.0
                removed_cost = average * units
                state["units"] -= units
                state["cost"] -= removed_cost
                cash += gross - tx["commission_tl"]
                total_sold += gross
                realized += gross - tx["commission_tl"] - removed_cost

        instruments = {item.ticker: item for item in self.market_repository.list_instruments()}
        positions: list[dict[str, Any]] = []
        market_value = 0.0
        remaining_cost = 0.0
        for ticker, state in holdings.items():
            if state["units"] <= 1e-9:
                continue
            bars = prices[ticker]
            latest_date, latest = bars[-1]
            value = state["units"] * latest.adjusted
            cost = state["cost"]
            market_value += value
            remaining_cost += cost
            instrument = instruments.get(ticker)
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
            "return_pct": _pct(total_value, total_bought) if total_bought else None,
        }
        return {
            "transactions": [
                {**tx, "trade_date": tx["trade_date"].isoformat()} for tx in transactions
            ],
            "positions": sorted(positions, key=lambda row: row["value"], reverse=True),
            "totals": totals,
            "benchmark": benchmark["summary"],
            "series": benchmark["series"],
        }

    # ------------------------------------------------------------------
    # Trade validation + persistence
    # ------------------------------------------------------------------
    def add_transaction(
        self,
        user_id: int,
        portfolio_id: int,
        payload: dict[str, Any],
        *,
        limit: int = 500,
    ) -> int:
        ticker_input = str(payload.get("ticker") or "").strip().upper()
        code = ticker_input.removesuffix(".IS")
        instrument = self.market_repository.get_instrument(code)
        if instrument is None:
            raise TradeError("Hisse bulunamadı.")
        side = str(payload.get("side") or "").lower()
        if side not in VALID_SIDES:
            raise TradeError("Yön alış veya satış olmalı.")
        try:
            trade_date = date.fromisoformat(str(payload.get("trade_date") or ""))
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
            commission = float(payload.get("commission_tl") or 0.0)
        except (TypeError, ValueError) as exc:
            raise TradeError("Adet, fiyat ve komisyon sayı olmalı.") from exc
        if quantity <= 0 or price <= 0:
            raise TradeError("Adet ve fiyat sıfırdan büyük olmalı.")
        if commission < 0:
            raise TradeError("Komisyon negatif olamaz.")

        if side == "sell":
            held = self._held_units(user_id, portfolio_id, instrument.ticker, trade_date)
            point = self._price_on(self._prices(instrument.ticker, trade_date), trade_date)
            if point is None:
                raise TradeError("Satış tarihinde fiyat verisi yok.")
            units = quantity * point.raw / point.adjusted
            if units > held + 1e-9:
                raise TradeError("Elde olandan fazla satış girilemez.")

        return self.user_repository.add_transaction(
            user_id,
            portfolio_id,
            {
                "ticker": instrument.ticker,
                "side": side,
                "trade_date": trade_date,
                "quantity": quantity,
                "price": price,
                "commission_tl": commission,
                "note": payload.get("note"),
            },
            limit=limit,
        )

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

        days = [day for day in sorted(xu) if day >= start]
        series: list[dict[str, Any]] = []
        units_by_ticker: dict[str, float] = {}
        for day in days:
            for tx in grouped.get(day, []):
                point = self._price_on(prices[tx["ticker"]], day)
                if point is None:
                    continue
                gross = tx["quantity"] * tx["price"]
                amount = (
                    gross + tx["commission_tl"]
                    if tx["side"] == "buy"
                    else -(gross - tx["commission_tl"])
                )
                day_xu = xu_on(day)
                if day_xu:
                    xu_units += amount / day_xu
                mm_day = mm_on(day)
                if mm_day:
                    mm_units += amount / mm_day
                if tx["side"] == "sell":
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
