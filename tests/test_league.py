"""Strategy league: statements math, rules, service and İş Yatırım client."""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from bist_bot.data import isyatirim
from bist_bot.market_calendar import TR
from bist_bot.services.league_service import LeagueService
from bist_bot.strategy.league import SPECS, LeagueInputs, build_fundamentals, decide_league

DAYS = pd.bdate_range("2025-01-01", periods=300)
TICKERS = [f"S{k:02d}.IS" for k in range(60)]


def test_build_fundamentals_ttm_quarter_and_lag():
    raw = {
        "2024/03": {"2O": 100, "3Z": 10, "3C": 50},
        "2024/12": {"2O": 120, "3Z": 60, "3C": 250},
        "2025/03": {"2O": 130, "3Z": 20, "3C": 80},
    }
    f = build_fundamentals(raw)
    q1 = f.loc[pd.Timestamp("2025-06-15")]  # Q1 statement usable from June 15
    assert q1["ttm"] == pytest.approx(20 + 60 - 10)
    assert q1["ni_q"] == pytest.approx(20) and q1["ni_q_ly"] == pytest.approx(10)
    assert q1["sales_q"] / q1["sales_q_ly"] == pytest.approx(80 / 50)
    assert pd.Timestamp("2025-04-15") in f.index  # FY 2024 usable from April 15


def test_published_quarters_skip_unpublished():
    assert isyatirim.published_quarters(date(2026, 9, 24), 3) == [(2026, 6), (2026, 3), (2025, 12)]
    assert isyatirim.published_quarters(date(2026, 9, 14), 1) == [(2026, 3)]


def _inputs(index_return: float, cash: float = 0.30) -> LeagueInputs:
    k = np.arange(60)
    adj = pd.DataFrame(
        {t: 10 * (1 + i * 1e-4) ** np.arange(len(DAYS)) for i, t in zip(k, TICKERS, strict=True)},
        index=DAYS,
    )
    mcap = pd.DataFrame(1e9, index=DAYS, columns=TICKERS)
    volume = pd.DataFrame(1e6, index=DAYS, columns=TICKERS)
    fund = {}
    for i, t in enumerate(TICKERS):
        # equity rises with i (V1), quarterly profit growth falls with i (E1).
        fund[t] = build_fundamentals(
            {
                "2024/03": {"2O": 100.0 + i, "3Z": 10.0, "3C": 50.0},
                "2024/12": {"2O": 100.0 + i, "3Z": 40.0, "3C": 200.0},
                "2025/03": {"2O": 100.0 + i, "3Z": 10.0 + (60 - i), "3C": 50.0 + i},
            }
        )
    daily = (1 + index_return) ** (1 / 252) - 1
    index = pd.Series(1000 * (1 + daily) ** np.arange(len(DAYS)), index=DAYS)
    return LeagueInputs(adj, mcap, volume, fund, index, TICKERS, cash)


def test_decide_league_rules_regime_on():
    regime, w = decide_league(_inputs(0.5), DAYS[-1].date())
    assert regime is True
    assert set(w) == {s.name for s in SPECS}
    liquid = set(TICKERS)  # all equally liquid; 50 of 60 kept (ties by order)
    assert len(w["C6 EW50"]) == 50 and set(w["C6 EW50"]) <= liquid
    assert len(w["C1 MOM5"]) == 5 and len(w["C2 MOM20"]) == 20
    assert w["A2 T2"] == {"XU100.IS": 1.0}
    universe = set(w["C6 EW50"])
    top_v1 = sorted(universe, key=lambda t: int(t[1:3]), reverse=True)[:10]
    assert set(w["A5 V1"]) == set(top_v1)  # highest equity / same mcap
    top_e1 = sorted(universe, key=lambda t: int(t[1:3]))[:10]
    assert set(w["A3 E1"]) == set(top_e1)  # largest profit growth
    assert all(abs(sum(x.values()) - 1) < 1e-9 for x in w.values() if x)


def test_decide_league_regime_off_moves_regime_strategies_to_cash():
    regime, w = decide_league(_inputs(0.10), DAYS[-1].date())
    assert regime is False
    for spec in SPECS:
        assert (w[spec.name] == {}) == spec.regime


def test_league_service_writes_ledgers_once(tmp_path, monkeypatch):
    inp = _inputs(0.5)
    loader = MagicMock(return_value=(inp.adj_close, inp.mcap, inp.volume_tl, inp.fundamentals))
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = pd.DataFrame({"close": inp.index_close})
    notifier = MagicMock()
    monkeypatch.setattr("bist_bot.services.league_service.pit_members", lambda _d: list(TICKERS))
    monkeypatch.setattr(
        "bist_bot.services.league_service.is_last_bist_session_of_month",
        lambda d: d == DAYS[-1].date(),
    )
    svc = LeagueService(
        fetcher,
        notifier,
        SimpleNamespace(LEAGUE_ENABLED=True, MONTHLY_PORTFOLIO_CASH_12M_RETURN_PCT=30.0),
        results_dir=tmp_path,
        member_loader=loader,
    )
    now = datetime.combine(DAYS[-1].date(), datetime.min.time(), TR)
    assert svc.run_if_due(now) is not None
    assert svc.run_if_due(now) is None
    state = json.loads((tmp_path / "league_state.json").read_text())
    assert len(state["strategies"]) == len(SPECS)
    hist = pd.read_csv(tmp_path / "league_history.csv")
    assert len(hist) == len(SPECS)
    assert "Strateji Ligi" in notifier.send_message.call_args[0][0]


def test_fetch_statements_pads_to_four_periods():
    session = MagicMock()
    response = MagicMock(ok=True)
    response.json.return_value = {"value": [{"itemCode": "2O", "value1": "5", "value2": "6"}]}
    session.get.return_value = response
    out = isyatirim.fetch_statements("ABC", [(2026, 6), (2026, 3)], session)
    params = session.get.call_args.kwargs["params"]
    assert {k for k in params if k.startswith("period")} == {
        "period1",
        "period2",
        "period3",
        "period4",
    }
    assert out == {"2026/06": {"2O": 5.0}, "2026/03": {"2O": 6.0}}
