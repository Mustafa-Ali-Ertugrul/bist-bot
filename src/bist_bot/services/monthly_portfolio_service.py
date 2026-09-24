"""Monthly portfolio (M2) paper track record.

Runs once per month, after the EOD pass of the last BIST session of the month:
computes the M2 target portfolio (strategy/monthly_portfolio.py), marks the
previous month's paper portfolio to market, records it next to XU100 buy-and-
hold and the money-market fund, and announces it on Telegram.

Paper fills use the decision-day close (the research used the next day's
close); the uninvested share earns the configured money-market rate.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import is_last_bist_session_of_month
from bist_bot.strategy.monthly_portfolio import MonthlyPortfolioDecision, decide, pit_members

logger = get_logger(__name__, component="monthly_portfolio")

INDEX_TICKER = "XU100.IS"
HISTORY_PERIOD = "2y"
COST_PER_SIDE = 0.0035  # research cost model: commission + BSMV + spread/slippage
MIN_MEMBER_FRAMES = 50
HISTORY_FIELDS = [
    "date",
    "regime_on",
    "index_12m_return",
    "cash_12m_return",
    "holdings",
    "period_return",
    "turnover",
    "nav",
    "index_nav",
    "cash_nav",
]


class MonthlyPortfolioService:
    def __init__(
        self,
        fetcher: Any,
        notifier: Any,
        settings: Any = default_settings,
        results_dir: str | Path = "results",
    ) -> None:
        self.fetcher = fetcher
        self.notifier = notifier
        self.settings = settings
        self.results_dir = Path(results_dir)
        self.state_path = self.results_dir / "monthly_portfolio_state.json"
        self.history_path = self.results_dir / "monthly_portfolio_history.csv"

    def run_if_due(self, now: datetime) -> MonthlyPortfolioDecision | None:
        """Rebalance on the last session of the month, at most once per day."""
        if not getattr(self.settings, "MONTHLY_PORTFOLIO_ENABLED", False):
            return None
        today = now.date()
        if not is_last_bist_session_of_month(today):
            return None
        if self._load_state().get("last_rebalance") == today.isoformat():
            return None
        return self.rebalance(today)

    def rebalance(self, as_of: date) -> MonthlyPortfolioDecision:
        members = pit_members(as_of)
        close, volume = self._fetch(members)
        index_frame = self._fetch_one(INDEX_TICKER)
        if index_frame is None:
            raise RuntimeError("XU100 history unavailable")
        cash_pct = float(getattr(self.settings, "MONTHLY_PORTFOLIO_CASH_12M_RETURN_PCT", 32.0))
        decision = decide(
            close, volume, index_frame["close"], members, cash_pct / 100.0, as_of=as_of
        )
        prices = close.loc[: pd.Timestamp(as_of)].ffill().iloc[-1]
        index_price = float(index_frame["close"].loc[: pd.Timestamp(as_of)].iloc[-1])
        row = self._update_ledger(decision, prices, index_price, cash_pct)
        logger.info(
            "monthly_portfolio_rebalanced",
            as_of=decision.as_of.isoformat(),
            regime_on=decision.regime_on,
            holdings=",".join(decision.weights),
            nav=row["nav"],
        )
        self.notifier.send_message(self._format_message(decision, row))
        return decision

    # ------------------------------------------------------------------
    def _fetch_one(self, ticker: str) -> pd.DataFrame | None:
        df = self.fetcher.fetch_single(ticker, period=HISTORY_PERIOD, interval="1d")
        if df is None or len(df) == 0 or "close" not in df.columns:
            return None
        df = df.copy()
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df[~df.index.duplicated(keep="last")]

    def _fetch(self, members: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
        closes: dict[str, pd.Series] = {}
        volumes: dict[str, pd.Series] = {}
        for ticker in members:
            df = self._fetch_one(ticker)
            if df is None or "volume" not in df.columns:
                continue
            closes[ticker] = df["close"]
            volumes[ticker] = df["volume"]
        if len(closes) < MIN_MEMBER_FRAMES:
            raise RuntimeError(f"only {len(closes)}/{len(members)} member histories fetched")
        return pd.DataFrame(closes), pd.DataFrame(volumes)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _update_ledger(
        self,
        decision: MonthlyPortfolioDecision,
        prices: pd.Series,
        index_price: float,
        cash_pct: float,
    ) -> dict[str, Any]:
        state = self._load_state()
        nav = float(state.get("nav", 1.0))
        index_nav = float(state.get("index_nav", 1.0))
        cash_nav = float(state.get("cash_nav", 1.0))
        drifted: dict[str, float] = {}
        period_growth = 1.0
        if state:
            days = (decision.as_of - date.fromisoformat(state["last_rebalance"])).days
            cash_growth = (1 + float(state["cash_rate_pct"]) / 100.0) ** (days / 365.0)
            holdings = state.get("holdings", {})
            growth = {}
            for ticker, pos in holdings.items():
                price = prices.get(ticker)
                growth[ticker] = float(price) / pos["price"] if pd.notna(price) else 1.0
            invested = sum(pos["weight"] for pos in holdings.values())
            period_growth = (
                sum(pos["weight"] * growth[t] for t, pos in holdings.items())
                + (1 - invested) * cash_growth
            )
            drifted = {t: pos["weight"] * growth[t] / period_growth for t, pos in holdings.items()}
            index_nav *= index_price / float(state["index_price"])
            cash_nav *= cash_growth
        tickers = set(drifted) | set(decision.weights)
        turnover = sum(abs(decision.weights.get(t, 0.0) - drifted.get(t, 0.0)) for t in tickers)
        nav *= period_growth * (1 - turnover * COST_PER_SIDE)

        new_state = {
            "last_rebalance": decision.as_of.isoformat(),
            "nav": nav,
            "index_nav": index_nav,
            "cash_nav": cash_nav,
            "index_price": index_price,
            "cash_rate_pct": cash_pct,
            "holdings": {
                t: {"weight": w, "price": float(prices[t])} for t, w in decision.weights.items()
            },
        }
        row = {
            "date": decision.as_of.isoformat(),
            "regime_on": decision.regime_on,
            "index_12m_return": decision.index_12m_return,
            "cash_12m_return": decision.cash_12m_return,
            "holdings": " ".join(decision.weights),
            "period_return": period_growth - 1,
            "turnover": turnover,
            "nav": nav,
            "index_nav": index_nav,
            "cash_nav": cash_nav,
        }
        self.results_dir.mkdir(parents=True, exist_ok=True)
        write_header = not self.history_path.exists()
        with self.history_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
        self.state_path.write_text(json.dumps(new_state, indent=1), encoding="utf-8")
        return row

    @staticmethod
    def _format_message(decision: MonthlyPortfolioDecision, row: dict[str, Any]) -> str:
        idx_ret = decision.index_12m_return
        idx_txt = f"%{idx_ret * 100:+.1f}" if idx_ret is not None else "yetersiz veri"
        cash_txt = f"%{decision.cash_12m_return * 100:.1f}"
        if decision.regime_on:
            regime = f"✅ Hisse (XU100 12 ay {idx_txt} > fon {cash_txt})"
            names = ", ".join(t.removesuffix(".IS") for t in decision.weights)
            body = f"Portföy (eşit ağırlık, {len(decision.weights)} hisse): {names}"
        else:
            regime = f"🛡️ Fon (XU100 12 ay {idx_txt} ≤ fon {cash_txt})"
            body = "Portföy: tamamı para piyasası fonunda"
        return (
            f"📅 <b>Aylık Portföy (paper)</b> — {decision.as_of.strftime('%d.%m.%Y')}\n"
            f"Rejim: {regime}\n{body}\n\n"
            f"Başlangıçtan beri: Portföy %{(row['nav'] - 1) * 100:+.1f} | "
            f"XU100 %{(row['index_nav'] - 1) * 100:+.1f} | Fon %{(row['cash_nav'] - 1) * 100:+.1f}\n"
            "⚠️ Paper test kaydıdır, yatırım tavsiyesi değildir."
        )


__all__ = ["MonthlyPortfolioService"]
