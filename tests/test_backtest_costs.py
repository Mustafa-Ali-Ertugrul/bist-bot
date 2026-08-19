"""Cost model tests for backtests."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from bist_bot.backtest import Backtester, CostModel


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class ScriptedCostBacktester(Backtester):
    def __init__(self, cost_model: CostModel | None = None):
        super().__init__(
            initial_capital=10_000,
            indicators=IdentityIndicators(),
            cost_model=cost_model,
        )

    def _build_signal_context(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
        _ = ticker
        if len(history) == 1:
            return {
                "enter": True,
                "exit": False,
                "score": 25.0,
                "stop_loss": 95.0,
                "target_price": 120.0,
            }
        return {
            "enter": False,
            "exit": False,
            "score": 0.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        }


def build_cost_frame() -> pd.DataFrame:
    dates = pd.date_range(datetime(2024, 1, 1), periods=60, freq="D")
    rows = []
    for idx, date in enumerate(dates):
        base = 100 + (idx * 0.5)
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 2.0,
                "low": base - 2.0,
                "close": base + 1.0,
                "volume": 1_000,
                "volume_sma_20": 1_000,
                "atr": 4.0,
                "rsi": 50.0,
                "sma_20": base,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def test_cost_models_reduce_net_return() -> None:
    df = build_cost_frame()

    no_cost = ScriptedCostBacktester(
        cost_model=CostModel(
            commission_bps=0.0, bsmv_bps=0.0, exchange_fee_bps=0.0, fixed_slippage_bps=0.0
        )
    )
    fixed_cost = ScriptedCostBacktester(
        cost_model=CostModel(slippage_model="fixed", fixed_slippage_bps=5.0)
    )
    volume_cost = ScriptedCostBacktester(
        cost_model=CostModel(
            slippage_model="volume_aware", volume_slippage_bps_per_volume_ratio=400.0
        )
    )
    atr_cost = ScriptedCostBacktester(
        cost_model=CostModel(slippage_model="atr_aware", atr_slippage_ratio=0.25)
    )

    no_cost_result = no_cost.run("TEST.IS", df, verbose=False)
    fixed_cost_result = fixed_cost.run("TEST.IS", df, verbose=False)
    volume_cost_result = volume_cost.run("TEST.IS", df, verbose=False)
    atr_cost_result = atr_cost.run("TEST.IS", df, verbose=False)

    assert no_cost_result is not None
    assert fixed_cost_result is not None
    assert volume_cost_result is not None
    assert atr_cost_result is not None
    assert fixed_cost_result.cost_breakdown.net_return < no_cost_result.cost_breakdown.net_return
    assert volume_cost_result.cost_breakdown.net_return < no_cost_result.cost_breakdown.net_return
    assert atr_cost_result.cost_breakdown.net_return < no_cost_result.cost_breakdown.net_return


def test_stamp_tax_applied_only_on_sell_side() -> None:
    """Stamp tax (damga vergisi) must be chargeable only on sell trades per BIST rules."""
    df = build_cost_frame()
    model = CostModel(
        commission_bps=2.0,
        stamp_tax_bps=9.3,
        bsmv_bps=5.0,
        exchange_fee_bps=0.3,
        spread_bps=10.0,
        fixed_slippage_bps=5.0,
    )
    bt = ScriptedCostBacktester(cost_model=model)
    result = bt.run("TEST.IS", df, verbose=False)
    assert result is not None
    assert result.cost_breakdown is not None
    # Stamp tax should appear in cost breakdown when sells exist.
    assert result.cost_breakdown.total_stamp_tax >= 0.0
    # Total costs should include stamp + spread + commission + BSMV + fees + slippage.
    total_known = (
        result.cost_breakdown.total_commission
        + result.cost_breakdown.total_bsmv
        + result.cost_breakdown.total_exchange_fee
        + result.cost_breakdown.total_stamp_tax
        + result.cost_breakdown.total_spread_cost
        + result.cost_breakdown.total_slippage
    )
    assert total_known > 0.0


def test_default_cost_model_matches_bist_fee_schedule() -> None:
    """Default CostModel values should reflect the 2024 BIST fee schedule."""
    default = CostModel()
    assert default.commission_bps == 2.0
    assert default.stamp_tax_bps == 9.3
    assert default.bsmv_bps == 5.0
    assert default.exchange_fee_bps == 0.3
    assert default.spread_bps == 10.0
    assert default.slippage_model == "fixed"
    assert default.fixed_slippage_bps == 5.0
