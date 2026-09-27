"""Overnight close->open paper rules (strategy/overnight.py, services/overnight_service.py)."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from bist_bot.notifier import TR
from bist_bot.scheduler import MarketScheduler
from bist_bot.services import overnight_service as svc_mod
from bist_bot.services.overnight_service import OvernightService
from bist_bot.strategy import overnight as rules

DAY = pd.Timestamp("2026-09-28")  # Monday
NEXT = pd.Timestamp("2026-09-29")
TICKERS = [f"T{i:02d}.IS" for i in range(25)]


def test_pick_rules():
    today = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [11.0, 10.5, 10.0, 12.0],
            "low": [9.0, 9.5, 10.0, 8.0],
            "close": [9.2, 10.4, 10.0, 11.9],
        },
        index=["A", "B", "C", "D"],
    )
    picks = rules.pick(today)
    assert picks["O1"] == ["A", "B", "C", "D"]
    assert picks["O2"][0] == "A"  # biggest intraday loss first
    assert picks["O3"][:2] == ["D", "B"]  # closes nearest the high
    assert "C" not in picks["O3"]  # zero range has no close location


def test_liquid_universe_ranks_by_median_traded_value_and_needs_history():
    idx = pd.bdate_range("2026-06-01", periods=60)
    daily = {
        "BIG": pd.DataFrame({"close": 10.0, "volume": 1000.0}, index=idx),
        "SMALL": pd.DataFrame({"close": 10.0, "volume": 10.0}, index=idx),
        "NEW": pd.DataFrame({"close": 10.0, "volume": 1e9}, index=idx[-10:]),
    }
    assert rules.liquid_universe(daily, ["SMALL", "BIG", "NEW"], idx[-1]) == ["BIG", "SMALL"]


def test_basket_return_uses_names_priced_on_both_legs():
    gross, n = rules.basket_return({"A": 10.0, "B": 20.0, "C": 5.0}, {"A": 11.0, "B": 19.0})
    assert n == 2 and gross == pytest.approx((0.10 - 0.05) / 2)


class FakeFetcher:
    """Daily bars up to DAY (or NEXT once ``advance()``), one 10:15 TR bar on NEXT."""

    def __init__(self):
        idx = pd.bdate_range(end=DAY, periods=70)
        self.daily, self.next_open, self.bar_1030 = {}, {}, {}
        for i, t in enumerate(TICKERS):
            df = pd.DataFrame(
                {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0 + i},
                index=idx,
            )
            # DAY: intraday change -i/10 %, close location i/24
            df.loc[DAY, ["open", "low", "high"]] = [100.0, 95.0, 105.0]
            df.loc[DAY, "close"] = 95.0 + 10.0 * i / 24
            self.daily[t] = df
            self.next_open[t] = df.loc[DAY, "close"] * (1 + i / 1000)
            self.bar_1030[t] = df.loc[DAY, "close"] * (1 - i / 1000)
        self.advanced = False

    def advance(self):
        self.advanced = True

    def fetch_single(self, ticker, period=None, interval=None, force=False):
        if interval == "15m":
            if not self.advanced:
                return None
            ts = pd.Timestamp("2026-09-29 07:15")  # 10:15 TR in naive UTC
            return pd.DataFrame({"close": [self.bar_1030[ticker]]}, index=[ts])
        df = self.daily[ticker]
        if self.advanced:
            o = self.next_open[ticker]
            row = pd.DataFrame(
                {"open": o, "high": o, "low": o, "close": o, "volume": 1.0}, index=[NEXT]
            )
            df = pd.concat([df, row])
        return df


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "pit_members", lambda day: list(TICKERS))
    fetcher, notifier = FakeFetcher(), MagicMock()
    s = OvernightService(fetcher, notifier, SimpleNamespace(OVERNIGHT_ENABLED=True), tmp_path)
    return s, fetcher, notifier


def at(day: pd.Timestamp, hh: int, mm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TR)


def ledger(s: OvernightService) -> list[dict[str, str]]:
    with s.history_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_evening_list_then_morning_exits(service):
    s, fetcher, notifier = service
    s.run_if_due(at(DAY, 17, 30))
    assert not notifier.send_message.called  # before close - 15 min

    s.run_if_due(at(DAY, 17, 46))
    night = json.loads(s.state_path.read_text(encoding="utf-8"))["nights"]["2026-09-28"]
    assert night["source"] == "list"
    assert night["picks"]["O2"] == TICKERS[:10]  # biggest intraday losers
    assert night["picks"]["O3"] == TICKERS[::-1][:10]  # closes nearest the high
    assert "Gece listesi" in notifier.send_message.call_args.args[0]

    s.run_if_due(at(DAY, 18, 20))
    assert notifier.send_message.call_count == 1  # idempotent

    fetcher.advance()
    s.run_if_due(at(NEXT, 10, 30))
    assert not s.history_path.exists()  # waits for the 10:30 bar to close

    s.run_if_due(at(NEXT, 10, 50))
    rows = ledger(s)
    assert {(r["rule"], r["exit"]) for r in rows} == {
        (k, e) for k in rules.RULES for e in ("open", "10:30")
    }
    o3 = next(r for r in rows if r["rule"] == "O3" and r["exit"] == "open")
    top10 = [TICKERS.index(t) for t in night["picks"]["O3"]]
    assert float(o3["gross"]) == pytest.approx(np.mean([i / 1000 for i in top10]), abs=1e-6)
    assert float(o3["net"]) == pytest.approx(float(o3["gross"]) - 2 * rules.COST_PER_SIDE, abs=1e-6)
    assert o3["days"] == "1"
    assert "Gece sonucu" in notifier.send_message.call_args.args[0]
    assert json.loads(s.state_path.read_text(encoding="utf-8"))["nights"] == {}

    s.run_if_due(at(NEXT, 11, 50))
    assert len(ledger(s)) == 6  # a closed night is not written twice


def test_missed_evening_is_picked_after_the_close(service):
    s, _, notifier = service
    s.run_if_due(at(DAY, 19, 0))
    night = json.loads(s.state_path.read_text(encoding="utf-8"))["nights"]["2026-09-28"]
    assert night["source"] == "eod"
    assert "geç" in notifier.send_message.call_args.args[0]


def test_night_without_open_prices_is_dropped_late_in_the_day(service, monkeypatch):
    s, fetcher, notifier = service
    s.run_if_due(at(DAY, 17, 46))
    fetcher.advance()
    monkeypatch.setattr(fetcher, "next_open", {t: np.nan for t in TICKERS})
    s.run_if_due(at(NEXT, 11, 0))
    assert "2026-09-28" in json.loads(s.state_path.read_text(encoding="utf-8"))["nights"]
    s.run_if_due(at(NEXT, 17, 5))
    assert json.loads(s.state_path.read_text(encoding="utf-8"))["nights"] == {}
    assert not s.history_path.exists()
    assert "kayda geçmedi" in notifier.send_message.call_args.args[0]


def test_disabled_and_holiday_are_noops(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "pit_members", lambda day: list(TICKERS))
    notifier = MagicMock()
    off = OvernightService(
        FakeFetcher(), notifier, SimpleNamespace(OVERNIGHT_ENABLED=False), tmp_path
    )
    off.run_if_due(at(DAY, 17, 46))
    on = OvernightService(
        FakeFetcher(), notifier, SimpleNamespace(OVERNIGHT_ENABLED=True), tmp_path
    )
    on.run_if_due(at(pd.Timestamp("2026-09-27"), 17, 46))  # Sunday
    assert not notifier.send_message.called
    assert not on.state_path.exists()


def test_scheduler_runs_overnight_after_eod_and_isolates_errors():
    overnight = MagicMock()
    overnight.run_if_due.side_effect = RuntimeError("boom")
    notifier = MagicMock()
    sched = MarketScheduler(MagicMock(), notifier, settings=SimpleNamespace(), overnight=overnight)
    now = at(DAY, 18, 20)
    sched._run_monthly_portfolio(now)
    sched._run_overnight(now)
    assert overnight.run_if_due.call_count == 2
    assert "Gece stratejisi" in notifier.send_message.call_args.args[0]
