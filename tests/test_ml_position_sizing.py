from __future__ import annotations

import pandas as pd

from bist_bot.risk import RiskLevels, RiskManager


def build_frame(liquidity_multiplier: float = 1.0) -> pd.DataFrame:
    rows = []
    for idx in range(30):
        rows.append(
            {
                "open": 100 + idx,
                "high": 102 + idx,
                "low": 99 + idx,
                "close": 101 + idx,
                "volume": 10000 * liquidity_multiplier,
                "atr": 2.0,
            }
        )
    return pd.DataFrame(rows)


def test_probability_sizing_applies_fractional_kelly_cap() -> None:
    manager = RiskManager(capital=10000)
    manager.max_position_cap_pct = 10.0
    manager.kelly_fraction_scale = 0.25
    levels = RiskLevels(
        final_stop=120.0,
        final_target=150.0,
        position_size=40,
        volatility_scale=1.0,
        correlation_scale=1.0,
    )
    price = 130.0

    adjusted = manager.apply_signal_probability(build_frame(), price, levels, 0.60)

    assert adjusted.signal_probability == 0.6
    assert adjusted.kelly_fraction > 0
    assert adjusted.position_size <= 7


def test_probability_sizing_blocks_low_liquidity() -> None:
    manager = RiskManager(capital=10000)
    manager.min_liquidity_value_tl = 2_000_000
    levels = RiskLevels(final_stop=120.0, final_target=150.0, position_size=20)

    adjusted = manager.apply_signal_probability(
        build_frame(liquidity_multiplier=0.5), 130.0, levels, 0.70
    )

    assert adjusted.blocked_by_liquidity is True
    assert adjusted.position_size == 0


def test_probability_sizing_blocks_when_daily_loss_cap_is_hit() -> None:
    manager = RiskManager(capital=10000)
    manager.daily_loss_cap_pct = 2.0
    manager.set_daily_realized_pnl(-250.0)
    levels = RiskLevels(final_stop=120.0, final_target=150.0, position_size=20)

    adjusted = manager.apply_signal_probability(
        build_frame(liquidity_multiplier=5.0), 130.0, levels, 0.70
    )

    assert adjusted.blocked_by_daily_loss is True
    assert adjusted.position_size == 0
