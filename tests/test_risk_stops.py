"""Behavior tests for risk/stops.py stop/target calculation functions."""

from __future__ import annotations

import os
import sys

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.risk.stops import (  # noqa: E402
    calc_atr_levels,
    calc_fibonacci,
    calc_fixed_percent,
    calc_support_resistance,
    calc_swing_levels,
    determine_final_levels,
)
from bist_bot.risk.models import RiskLevels  # noqa: E402


def _make_frame(prices: list[float], atr: float | None = None) -> pd.DataFrame:
    rows = []
    for i, close in enumerate(prices):
        rows.append(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "atr": atr,
            }
        )
    return pd.DataFrame(rows)


class TestCalcAtrLevels:
    def test_atr_levels_calculation(self):
        df = _make_frame([100.0] * 15, atr=2.0)
        levels = RiskLevels()
        result = calc_atr_levels(
            df, price=100.0, levels=levels, atr_stop_mult=2.0, atr_target_mult=3.0
        )

        assert result.stop_atr == 96.0
        assert result.target_atr == 106.0

    def test_atr_none_returns_unchanged_levels(self):
        df = _make_frame([100.0] * 15, atr=None)
        levels = RiskLevels()
        result = calc_atr_levels(
            df, price=100.0, levels=levels, atr_stop_mult=2.0, atr_target_mult=3.0
        )

        assert result.stop_atr == 0.0
        assert result.target_atr == 0.0


class TestCalcSupportResistance:
    def test_support_below_price(self):
        df = _make_frame([100.0, 101.0, 99.0, 102.0, 100.5] * 10)
        levels = RiskLevels()
        result = calc_support_resistance(df, price=105.0, levels=levels)

        assert result.stop_support > 0
        assert result.stop_support < 105.0

    def test_no_support_above_price(self):
        df = _make_frame([100.0] * 10)
        levels = RiskLevels()
        result = calc_support_resistance(df, price=50.0, levels=levels)

        assert result.stop_support == 0.0


class TestCalcFibonacci:
    def test_fibonacci_levels(self):
        df = _make_frame([100.0] * 70)
        df.iloc[-60:, df.columns.get_loc("high")] = 120.0
        df.iloc[-60:, df.columns.get_loc("low")] = 80.0

        levels = RiskLevels()
        result = calc_fibonacci(df, price=100.0, levels=levels)

        assert result.stop_fibonacci > 0
        assert result.target_fibonacci > 100.0

    def test_fibonacci_zero_diff_falls_back_to_swing_high(self):
        df = _make_frame([100.0] * 5)
        levels = RiskLevels()
        result = calc_fibonacci(df, price=100.0, levels=levels)

        assert result.stop_fibonacci == 0.0
        assert result.target_fibonacci == 100.0


class TestCalcFixedPercent:
    def test_fixed_percent_levels(self):
        levels = RiskLevels()
        result = calc_fixed_percent(
            price=100.0, levels=levels, fixed_stop_pct=5.0, fixed_target_pct=10.0
        )

        assert result.stop_percent == 95.0
        assert result.target_percent == 110.0

    def test_fixed_percent_negative_prices(self):
        levels = RiskLevels()
        result = calc_fixed_percent(
            price=50.0, levels=levels, fixed_stop_pct=5.0, fixed_target_pct=10.0
        )

        assert result.stop_percent == 47.5
        assert result.target_percent == 55.0


class TestCalcSwingLevels:
    def test_swing_lows_below_price(self):
        prices = []
        for i in range(40):
            if i % 10 == 2:
                prices.append(95.0)
            else:
                prices.append(100.0 + (i % 3))
        df = _make_frame(prices)
        levels = RiskLevels()
        result = calc_swing_levels(df, price=105.0, levels=levels)

        assert result.stop_swing > 0

    def test_swing_highs_above_price(self):
        prices = []
        for i in range(40):
            if i % 10 == 5:
                prices.append(115.0)
            else:
                prices.append(100.0 + (i % 3))
        df = _make_frame(prices)
        levels = RiskLevels()
        result = calc_swing_levels(df, price=100.0, levels=levels)

        assert result.target_swing > 100.0

    def test_insufficient_data(self):
        df = _make_frame([100.0] * 3)
        levels = RiskLevels()
        result = calc_swing_levels(df, price=100.0, levels=levels)

        assert result.stop_swing == 0.0
        assert result.target_swing == 0.0


class TestDetermineFinalLevels:
    def test_reasonable_stop_selected(self):
        levels = RiskLevels(
            stop_atr=92.0,
            target_atr=110.0,
            stop_support=98.0,
            target_resistance=108.0,
            stop_percent=95.0,
            target_percent=110.0,
        )
        result = determine_final_levels(price=100.0, levels=levels)

        assert result.final_stop == 98.0
        assert result.final_target == 108.0
        assert result.risk_pct < 0
        assert result.reward_pct > 0

    def test_fallback_to_valid_stops(self):
        levels = RiskLevels(
            stop_atr=0.0,
            stop_support=98.0,
            target_resistance=105.0,
        )
        result = determine_final_levels(price=100.0, levels=levels)

        assert result.final_stop == 98.0
        assert result.final_target == 105.0

    def test_fallback_to_fixed_percent(self):
        levels = RiskLevels()
        result = determine_final_levels(price=100.0, levels=levels)

        assert result.final_stop == levels.stop_percent
        assert result.final_target == levels.target_percent

    def test_confidence_high_with_low_std(self):
        levels = RiskLevels(
            stop_atr=96.0,
            stop_support=97.0,
            stop_fibonacci=98.0,
            stop_percent=95.0,
            target_atr=105.0,
            target_resistance=106.0,
            target_fibonacci=104.0,
            target_percent=110.0,
        )
        result = determine_final_levels(price=100.0, levels=levels)

        assert result.confidence == "confidence.high"

    def test_risk_reward_ratio_calculation(self):
        levels = RiskLevels(
            stop_atr=90.0,
            target_atr=110.0,
        )
        result = determine_final_levels(price=100.0, levels=levels)

        assert result.risk_reward_ratio == 1.0
        assert result.risk_pct == -10.0
        assert result.reward_pct == 10.0
