"""Month-end paper run of the strategy league (strategy/league.py).

After the EOD pass of the last BIST session of the month: fetches İş Yatırım
daily data + recent statements for the current BIST100 members, decides all
18 strategies, marks each paper portfolio to market and posts a league table
to the operator chat (not the customer group).
"""

from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.data import isyatirim
from bist_bot.market_calendar import is_last_bist_session_of_month
from bist_bot.services.paper_ledger import mark_to_market
from bist_bot.strategy.league import (
    INDEX_TICKER,
    SPECS,
    LeagueInputs,
    build_fundamentals,
    decide_league,
)
from bist_bot.strategy.monthly_portfolio import pit_members

logger = get_logger(__name__, component="league")

HISTORY_DAYS = 430  # > 252 bars + rebalance gap
STATEMENT_QUARTERS = 8
MIN_MEMBER_FRAMES = 50
HISTORY_FIELDS = [
    "date",
    "strategy",
    "regime_on",
    "holdings",
    "period_return",
    "turnover",
    "nav",
    "index_nav",
    "cash_nav",
]


class LeagueService:
    def __init__(
        self,
        index_fetcher: Any,
        notifier: Any,
        settings: Any = default_settings,
        results_dir: str | Path = "results",
        member_loader: Any = None,
    ) -> None:
        self.index_fetcher = index_fetcher
        self.notifier = notifier
        self.settings = settings
        self.results_dir = Path(results_dir)
        self.state_path = self.results_dir / "league_state.json"
        self.history_path = self.results_dir / "league_history.csv"
        self._member_loader = member_loader or self._load_members

    def run_if_due(self, now: datetime) -> dict[str, dict[str, float]] | None:
        if not getattr(self.settings, "LEAGUE_ENABLED", False):
            return None
        today = now.date()
        if not is_last_bist_session_of_month(today):
            return None
        if self._load_state().get("last_rebalance") == today.isoformat():
            return None
        return self.rebalance(today)

    def rebalance(self, as_of: date) -> dict[str, dict[str, float]]:
        members = pit_members(as_of)
        adj, mcap, volume, fundamentals = self._member_loader(members, as_of)
        index_frame = self.index_fetcher.fetch_single(INDEX_TICKER, period="2y", interval="1d")
        if index_frame is None or len(index_frame) == 0:
            raise RuntimeError("XU100 history unavailable")
        index_close = index_frame["close"].copy()
        index_close.index = pd.to_datetime(index_close.index).tz_localize(None).normalize()
        index_close = index_close[~index_close.index.duplicated(keep="last")]
        cash_pct = float(getattr(self.settings, "MONTHLY_PORTFOLIO_CASH_12M_RETURN_PCT", 32.0))

        regime_on, weights = decide_league(
            LeagueInputs(adj, mcap, volume, fundamentals, index_close, members, cash_pct / 100.0),
            as_of,
        )
        panel = adj.join(index_close.rename(INDEX_TICKER), how="outer")
        state = self._load_state()
        strategies = state.get("strategies", {})
        rows = []
        for spec in SPECS:
            new_state, row = mark_to_market(
                strategies.get(spec.name, {}),
                weights[spec.name],
                panel,
                INDEX_TICKER,
                as_of,
                cash_pct,
            )
            strategies[spec.name] = new_state
            rows.append({**row, "strategy": spec.name, "regime_on": regime_on})
        self._write(as_of, strategies, rows)
        logger.info("league_rebalanced", as_of=as_of.isoformat(), regime_on=regime_on)
        self.notifier.send_message(self._format_table(as_of, regime_on, rows))
        return weights

    # ------------------------------------------------------------------
    @staticmethod
    def _load_members(
        members: list[str], as_of: date
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
        start = as_of - timedelta(days=HISTORY_DAYS)
        quarters = isyatirim.published_quarters(as_of, STATEMENT_QUARTERS)
        session = requests.Session()

        def one(ticker: str):
            code = ticker.removesuffix(".IS")
            daily = isyatirim.fetch_daily(code, start, as_of, session)
            statements = isyatirim.fetch_statements(code, quarters, session)
            return ticker, daily, statements

        adj, mcap, vol, fund = {}, {}, {}, {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for ticker, daily, statements in pool.map(one, members):
                if daily.empty:
                    continue
                adj[ticker], mcap[ticker], vol[ticker] = (
                    daily["adj_close"],
                    daily["mcap"],
                    daily["volume_tl"],
                )
                if statements:
                    fund[ticker] = build_fundamentals(statements)
        if len(adj) < MIN_MEMBER_FRAMES:
            raise RuntimeError(f"only {len(adj)}/{len(members)} member histories fetched")
        return pd.DataFrame(adj), pd.DataFrame(mcap), pd.DataFrame(vol), fund

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write(self, as_of: date, strategies: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        write_header = not self.history_path.exists()
        with self.history_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
            if write_header:
                writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k) for k in HISTORY_FIELDS})
        payload = {"last_rebalance": as_of.isoformat(), "strategies": strategies}
        self.state_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    @staticmethod
    def _format_table(as_of: date, regime_on: bool, rows: list[dict[str, Any]]) -> str:
        ranked = sorted(rows, key=lambda r: r["nav"], reverse=True)
        lines = [f"{r['strategy']:<10} %{(r['nav'] - 1) * 100:+6.1f}" for r in ranked]
        ref = rows[0]
        regime = "✅ açık" if regime_on else "🛡️ kapalı (R'li stratejiler nakitte)"
        return (
            f"🏁 <b>Strateji Ligi (paper)</b> — {as_of.strftime('%d.%m.%Y')}\n"
            f"Rejim: {regime}\n<pre>"
            + "\n".join(lines)
            + f"\n{'XU100':<10} %{(ref['index_nav'] - 1) * 100:+6.1f}"
            + f"\n{'Fon':<10} %{(ref['cash_nav'] - 1) * 100:+6.1f}</pre>\n"
            "Başlangıçtan beri. Karar kriteri 12 ay: scripts/research/LEAGUE_PREREGISTRATION.md"
        )


__all__ = ["LeagueService"]
