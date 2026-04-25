"""Tests for BIST trading cost model."""

from __future__ import annotations

from bist_bot.risk.costs import DEFAULT_COSTS, TradingCosts


class TestTradingCosts:
    def test_buy_cost(self):
        costs = TradingCosts(commission_pct=0.0002)
        assert costs.buy_cost(100_000) == 20.0

    def test_sell_cost_includes_taxes(self):
        costs = TradingCosts(commission_pct=0.0002, stamp_tax_pct=0.00093, bsmv_pct=0.0005)
        total_pct = 0.0002 + 0.00093 + 0.0005
        expected = 100_000 * total_pct
        assert costs.sell_cost(100_000) == expected

    def test_round_trip(self):
        costs = TradingCosts(commission_pct=0.0002, stamp_tax_pct=0.00093, bsmv_pct=0.0005)
        buy_notional = 100_000
        sell_notional = 105_000
        expected = costs.buy_cost(buy_notional) + costs.sell_cost(sell_notional)
        assert costs.round_trip_cost(buy_notional, sell_notional) == expected

    def test_default_costs_immutable(self):
        assert DEFAULT_COSTS.commission_pct == 0.0002
        assert DEFAULT_COSTS.stamp_tax_pct == 0.00093
        assert DEFAULT_COSTS.bsmv_pct == 0.0005

    def test_zero_notional(self):
        assert DEFAULT_COSTS.buy_cost(0) == 0
        assert DEFAULT_COSTS.sell_cost(0) == 0

    def test_custom_costs(self):
        costs = TradingCosts(commission_pct=0.001)
        assert costs.buy_cost(10_000) == 10.0

    def test_sell_cost_higher_than_buy(self):
        notional = 50_000
        assert DEFAULT_COSTS.sell_cost(notional) > DEFAULT_COSTS.buy_cost(notional)

    def test_round_trip_symmetric_for_same_notional(self):
        notional = 100_000
        rt = DEFAULT_COSTS.round_trip_cost(notional, notional)
        assert rt == DEFAULT_COSTS.buy_cost(notional) + DEFAULT_COSTS.sell_cost(notional)
