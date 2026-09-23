"""Realistic (live-like) cost scenario tests — v2 toparlama planı §3.

Uses fully scripted bar data; no DB or network access.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from bist_bot.backtest import (
    REALISTIC_COSTS,
    compare_cost_scenarios,
    realistic_cost_model,
    realistic_cost_scenarios,
    realistic_execution,
)
from bist_bot.backtest.signal_replay import (
    ReplaySignal,
    SignalReplayEngine,
    build_cost_scenarios,
    calculate_cell_metrics,
)
from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import SignalType


def _bars(start: date, closes: list[float]) -> pd.DataFrame:
    dates = [date.fromordinal(start.toordinal() + i) for i in range(len(closes))]
    opens = [closes[0], *closes[:-1]]
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        }
    )


def _signal(signal_id: int | str = 1) -> ReplaySignal:
    return ReplaySignal(
        id=signal_id,
        ticker="AAA.IS",
        timestamp=datetime(2025, 1, 10, 9, 30, tzinfo=UTC),
        signal_type=SignalType.BUY.value,
        score=28.0,
        price=100.0,
        stop_loss=90.0,
        target_price=120.0,
        confidence="confidence.medium",
    )


def _replay(cost: str, delay: int, bars: pd.DataFrame):
    engine = SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())
    return engine.simulate_single_signal(
        _signal(), bars, cost_model_name=cost, dataset_name="raw", entry_delay_bars=delay
    )


def test_realistic_scenario_present_with_expected_values() -> None:
    scenarios = build_cost_scenarios()
    assert set(scenarios) == {"zero", "base", "stress", "realistic"}
    model = scenarios["realistic"]
    assert model.commission_bps == pytest.approx(REALISTIC_COSTS["commission_bps"])
    assert model.spread_bps == pytest.approx(REALISTIC_COSTS["spread_bps"])
    assert model.fixed_slippage_bps == pytest.approx(REALISTIC_COSTS["entry_slippage_bps"])
    # Base/zero/stress değişmedi (geriye uyumluluk).
    assert scenarios["zero"].commission_bps == 0.0
    assert scenarios["base"].commission_bps == 2.0
    assert scenarios["stress"].fixed_slippage_bps == 15.0


def test_realistic_commission_env_override() -> None:
    with settings.override(BACKTEST_REALISTIC_COMMISSION_BPS=25.0):
        assert realistic_cost_model().commission_bps == pytest.approx(25.0)
    assert realistic_cost_model().commission_bps == pytest.approx(15.0)


def test_realistic_costs_reduce_net_vs_zero() -> None:
    bars = _bars(date(2025, 1, 13), [100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
    # Aynı giriş gecikmesi: brüt aynı, fark yalnızca maliyetten gelir.
    zero_trade, zero_status = _replay("zero", 1, bars)
    realistic_trade, realistic_status = _replay("realistic", 1, bars)
    assert zero_status == realistic_status == "ok"
    assert zero_trade is not None and realistic_trade is not None
    assert realistic_trade.net_pnl_pct < zero_trade.net_pnl_pct
    assert realistic_trade.total_cost_bps > zero_trade.total_cost_bps

    metrics = {
        "zero": calculate_cell_metrics([zero_trade], 1),
        "realistic": calculate_cell_metrics([realistic_trade], 1),
    }
    report = compare_cost_scenarios(metrics)
    assert report["baseline"] == "zero"
    assert report["candidate"] == "realistic"
    assert report["avg_net_pnl_delta_pp"] < 0
    assert report["traded_delta"] == 0


def test_entry_delay_shifts_realistic_entry_by_latency() -> None:
    bars = _bars(date(2025, 1, 13), [100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    latency = realistic_execution().latency_bars
    assert latency == 1
    prompt, _ = _replay("realistic", 0, bars)
    delayed, status = _replay("realistic", latency, bars)
    assert status == "ok"
    assert prompt is not None and delayed is not None
    assert delayed.entry_date != prompt.entry_date
    assert delayed.entry_date == "2025-01-14"


def test_realistic_execution_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        realistic_execution(latency_bars=-1)
    with pytest.raises(ValueError):
        realistic_execution(entry_slippage_bps=-5.0)
    with pytest.raises(ValueError):
        realistic_execution(fill_probability=0.0)
    with pytest.raises(ValueError):
        realistic_execution(fill_probability=1.5)
    with pytest.raises(ValueError):
        realistic_cost_model(commission_bps=-1.0)


def test_compare_cost_scenarios_requires_both_sides() -> None:
    with pytest.raises(KeyError):
        compare_cost_scenarios({"zero": {}})
    with pytest.raises(KeyError):
        compare_cost_scenarios({"realistic": {}}, baseline="zero", candidate="missing")


def test_realistic_scenarios_helper_matches_builder() -> None:
    scenarios = realistic_cost_scenarios()
    assert scenarios["realistic"].commission_bps == pytest.approx(
        build_cost_scenarios()["realistic"].commission_bps
    )
