"""Paper ledger: returns recomputed from current (re-based) price history."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from bist_bot.services.paper_ledger import COST_PER_SIDE, mark_to_market

D0, D1 = date(2026, 9, 30), date(2026, 10, 30)
DAYS = pd.to_datetime([D0, D1])


def test_bonus_issue_rebase_is_not_a_loss():
    # First rebalance: provider shows 100 on D0.
    first = pd.DataFrame({"A.IS": [100.0], "XU100.IS": [1000.0]}, index=DAYS[:1])
    state, _ = mark_to_market({}, {"A.IS": 1.0}, first, "XU100.IS", D0, 0.0)
    # 1:1 bonus issue during the month; provider re-bases D0 to 50, D1 = 55.
    rebased = pd.DataFrame({"A.IS": [50.0, 55.0], "XU100.IS": [1000.0, 1100.0]}, index=DAYS)
    state, row = mark_to_market(state, {"A.IS": 1.0}, rebased, "XU100.IS", D1, 0.0)
    assert row["period_return"] == pytest.approx(0.10)
    assert row["index_nav"] == pytest.approx(1.10)
    assert row["turnover"] == pytest.approx(0.0)
    assert state["nav"] == pytest.approx((1 - COST_PER_SIDE) * 1.10)


def test_cash_share_earns_money_market_and_missing_price_is_flat():
    panel = pd.DataFrame({"A.IS": [10.0, 12.0], "XU100.IS": [1000.0, 1000.0]}, index=DAYS)
    state, _ = mark_to_market({}, {"A.IS": 0.5, "GONE.IS": 0.2}, panel, "XU100.IS", D0, 36.5)
    _, row = mark_to_market(state, {}, panel, "XU100.IS", D1, 36.5)
    cash_growth = 1.365 ** (30 / 365)
    expected = 0.5 * 1.2 + 0.2 * 1.0 + 0.3 * cash_growth
    assert row["period_return"] == pytest.approx(expected - 1)
    assert row["cash_nav"] == pytest.approx(cash_growth)
