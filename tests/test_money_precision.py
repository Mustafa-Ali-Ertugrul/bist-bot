"""Float precision regression: kuruş-exact accounting boundary (Round 21).

Binary float dust (0.1 + 0.2 != 0.3) must never leak into cash, fees,
notional, PnL, or order-fill state transitions.
"""

from __future__ import annotations

from bist_bot.execution.base import Order, OrderSide, OrderType
from bist_bot.execution.paper_broker import PaperBroker
from bist_bot.risk.costs import TradingCosts
from bist_bot.risk.money import (
    calc_cost,
    calc_notional,
    calc_pnl,
    is_zero_qty,
    quantize_money,
    quantize_price,
)


def test_classic_float_dust_is_gone() -> None:
    # 0.1 + 0.2 float'ta 0.30000000000000004'tür; money helper tam 0.30 verir.
    assert (0.1 + 0.2) != 0.3
    assert quantize_money(0.1 + 0.2) == 0.3


def test_notional_kurus_exact() -> None:
    # 3 x 19.99 = 59.97 tam kuruş olmalı, dust'suz.
    assert calc_notional(3, 19.99) == 59.97
    assert calc_notional(7, 0.07) == 0.49


def test_costs_kurus_exact() -> None:
    costs = TradingCosts(commission_pct=0.0002, stamp_tax_pct=0.00093, bsmv_pct=0.0005)
    # 100k sell: 100000 * 0.00163 = 163.00 tam (float'ta 163.00000000000003 olur).
    assert costs.sell_cost(100_000) == 163.0
    assert costs.buy_cost(100_000) == 20.0
    # Ham float çarpım dust üretse bile helper kuruşa sabitler.
    assert calc_cost(100_000, 0.00163) == 163.0


def test_paper_broker_cash_stays_kurus_exact() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    broker.submit_order("DUST.IS", OrderSide.BUY, 3, OrderType.MARKET, price=19.99)
    # Nakit her fill sonrası kuruşa quantize: dust birikmez.
    cash_str = f"{broker.cash:.2f}"
    assert broker.cash == round(broker.cash, 2)
    assert cash_str == f"{broker.cash:.2f}"
    # 59.97 notional + 0.01 fee (59.97*0.0002=0.011994 -> 0.01) = 59.98 gider.
    assert broker.cash == 100_000.0 - 59.97 - 0.01


def test_partial_fill_dust_never_blocks_filled_state() -> None:
    broker = PaperBroker(initial_cash=100_000.0, manual_confirm=True)
    result = broker.submit_order("DUST.IS", "BUY", 0.3, OrderType.LIMIT, price=10.0)
    order_id = result.order_id
    # 0.1 + 0.2 ile 0.3'lük emri parça parça doldur: float dust kalır ama
    # remaining_quantity epsilon ile 0 sayılmalı, state FILLED olmalı.
    assert broker.partial_fill(order_id, 0.1, 10.0) is True
    assert broker.partial_fill(order_id, 0.2, 10.0) is True
    order: Order = broker.orders[order_id]
    assert order.remaining_quantity() == 0.0
    from bist_bot.execution.base import OrderState

    assert order.state is OrderState.FILLED


def test_position_dust_never_survives_sell() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    broker.submit_order("DUST.IS", OrderSide.BUY, 0.3, OrderType.MARKET, price=10.0)
    assert len(broker.get_positions()) == 1
    broker.submit_order("DUST.IS", OrderSide.SELL, 0.1, OrderType.MARKET, price=11.0)
    broker.submit_order("DUST.IS", OrderSide.SELL, 0.2, OrderType.MARKET, price=11.0)
    # 0.30000000000000004 - 0.3 dust'u pozisyon diye yaşamamalı.
    assert broker.get_positions() == []


def test_calc_pnl_kurus_exact() -> None:
    # (19.99 - 19.50) * 100 = 49.00 tam; fee düşülmüş hali de kuruş-exact.
    assert calc_pnl(19.99, 19.50, 100) == 49.0
    assert calc_pnl(19.99, 19.50, 100, fees=1.63) == 47.37


def test_is_zero_qty_epsilon() -> None:
    assert is_zero_qty(0.3 - (0.1 + 0.2)) is True
    assert is_zero_qty(5e-10) is True
    assert is_zero_qty(0.01) is False


def test_quantize_price_4dp() -> None:
    assert quantize_price(10.12345) == 10.1235
    assert quantize_price(10.0) == 10.0
