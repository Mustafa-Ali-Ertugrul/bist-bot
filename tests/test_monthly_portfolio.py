"""Monthly portfolio (M2): rule, PIT membership, paper ledger and scheduler hook."""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from bist_bot.market_calendar import TR, is_last_bist_session_of_month
from bist_bot.scheduler import MarketScheduler
from bist_bot.services.monthly_portfolio_service import COST_PER_SIDE, MonthlyPortfolioService
from bist_bot.strategy import monthly_portfolio as mp

DAYS = pd.bdate_range("2025-01-01", periods=300)


def _panel(n: int = 60, illiquid: range = range(0)):
    """Stock k grows k*0.01% per day; volume 1 for ``illiquid`` names."""
    tickers = [f"S{k:02d}.IS" for k in range(n)]
    close = pd.DataFrame(
        {t: 10 * (1 + k * 1e-4) ** np.arange(len(DAYS)) for k, t in enumerate(tickers)},
        index=DAYS,
    )
    volume = pd.DataFrame(1e6, index=DAYS, columns=tickers)
    for k in illiquid:
        volume[tickers[k]] = 1.0
    return close, volume, tickers


def _index(total_return: float) -> pd.Series:
    daily = (1 + total_return) ** (1 / 252) - 1
    return pd.Series(100 * (1 + daily) ** np.arange(len(DAYS)), index=DAYS)


def test_regime_off_holds_cash():
    close, volume, tickers = _panel()
    d = mp.decide(close, volume, _index(0.20), tickers, cash_12m_return=0.30)
    assert d.regime_on is False
    assert d.weights == {}


def test_top_momentum_among_liquid_members():
    close, volume, tickers = _panel(illiquid=range(50, 60))
    d = mp.decide(close, volume, _index(0.50), tickers, cash_12m_return=0.30)
    assert d.regime_on is True
    # S50..S59 have the best momentum but are the 10 least liquid -> excluded.
    assert sorted(d.weights) == [f"S{k}.IS" for k in range(40, 50)]
    assert all(w == pytest.approx(0.1) for w in d.weights.values())


def test_non_members_and_short_history_excluded():
    close, volume, tickers = _panel()
    close.loc[DAYS[:100], "S59.IS"] = np.nan  # only 200 bars of history
    members = tickers[:55]  # S55..S58 are not members
    d = mp.decide(close, volume, _index(0.50), members, cash_12m_return=0.30)
    assert sorted(d.weights) == [f"S{k}.IS" for k in range(45, 55)]


def test_clean_prices_zeroes_split_artifact():
    s = pd.DataFrame({"A": [100.0, 101.0, 50.5, 51.0]})
    clean = mp.clean_prices(s)
    assert clean["A"].iloc[2] == pytest.approx(clean["A"].iloc[1])
    assert clean["A"].iloc[3] / clean["A"].iloc[2] == pytest.approx(51.0 / 50.5)


def test_pit_members_uses_quarter_of_date():
    q3 = mp.pit_members(date(2026, 8, 15))
    assert "ESEN.IS" in q3 and "AGHOL.IS" not in q3  # 2026 Q3 change set
    assert len(mp.pit_members(date(2016, 5, 1))) >= 100
    with pytest.raises(ValueError):
        mp.pit_members(date(2015, 1, 1))


def test_last_session_of_month():
    assert is_last_bist_session_of_month(date(2026, 9, 30)) is True
    assert is_last_bist_session_of_month(date(2026, 9, 29)) is False
    assert is_last_bist_session_of_month(date(2026, 10, 30)) is True  # Oct 31 is Saturday
    assert is_last_bist_session_of_month(date(2026, 10, 31)) is False


class _Fetcher:
    def __init__(self, frames):
        self.frames = frames

    def fetch_single(self, ticker, period=None, interval=None):
        return self.frames.get(ticker)


def _service(tmp_path, monkeypatch, close, volume, index, enabled=True):
    frames = {t: pd.DataFrame({"close": close[t], "volume": volume[t]}) for t in close.columns}
    frames["XU100.IS"] = pd.DataFrame({"close": index, "volume": 1.0})
    monkeypatch.setattr(
        "bist_bot.services.monthly_portfolio_service.pit_members", lambda _d: list(close.columns)
    )
    settings = SimpleNamespace(
        MONTHLY_PORTFOLIO_ENABLED=enabled, MONTHLY_PORTFOLIO_CASH_12M_RETURN_PCT=30.0
    )
    notifier = MagicMock()
    svc = MonthlyPortfolioService(_Fetcher(frames), notifier, settings, results_dir=tmp_path)
    return svc, notifier


def test_run_if_due_only_on_month_end_and_once(tmp_path, monkeypatch):
    close, volume, _ = _panel()
    svc, notifier = _service(tmp_path, monkeypatch, close, volume, _index(0.5))
    monkeypatch.setattr(
        "bist_bot.services.monthly_portfolio_service.is_last_bist_session_of_month",
        lambda d: d == DAYS[-1].date(),
    )
    assert svc.run_if_due(datetime.combine(DAYS[-2].date(), datetime.min.time(), TR)) is None
    now = datetime.combine(DAYS[-1].date(), datetime.min.time(), TR)
    assert svc.run_if_due(now) is not None
    assert svc.run_if_due(now) is None  # idempotent for the day
    assert notifier.send_message.call_count == 1
    assert "Aylık Portföy" in notifier.send_message.call_args[0][0]


def test_disabled_service_does_nothing(tmp_path, monkeypatch):
    close, volume, _ = _panel()
    svc, notifier = _service(tmp_path, monkeypatch, close, volume, _index(0.5), enabled=False)
    assert svc.run_if_due(datetime(2026, 9, 30, 18, 20, tzinfo=TR)) is None
    notifier.send_message.assert_not_called()


def test_ledger_marks_previous_portfolio_to_market(tmp_path, monkeypatch):
    close, volume, _ = _panel()
    index = _index(0.5)
    svc, _ = _service(tmp_path, monkeypatch, close, volume, index)
    first_day, second_day = DAYS[-22].date(), DAYS[-1].date()
    first = svc.rebalance(first_day)
    state = json.loads((tmp_path / "monthly_portfolio_state.json").read_text())
    assert state["nav"] == pytest.approx(1 - 1.0 * COST_PER_SIDE)  # full buy-in turnover

    svc.rebalance(second_day)
    hist = pd.read_csv(tmp_path / "monthly_portfolio_history.csv")
    assert len(hist) == 2
    expected_growth = np.mean(
        [close.loc[DAYS[-1], t] / close.loc[DAYS[-22], t] for t in first.weights]
    )
    assert hist["period_return"].iloc[1] == pytest.approx(expected_growth - 1)
    assert hist["index_nav"].iloc[1] == pytest.approx(index.iloc[-1] / index.iloc[-22])


def test_scheduler_isolates_monthly_failure():
    notifier = MagicMock()
    monthly = MagicMock()
    monthly.run_if_due.side_effect = RuntimeError("yahoo down")
    sched = MarketScheduler(MagicMock(), notifier, monthly_portfolio=monthly)
    sched._run_monthly_portfolio(datetime(2026, 9, 30, 18, 20, tzinfo=TR))
    assert "Aylık portföy" in notifier.send_message.call_args[0][0]
