"""Strategy threshold tests."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import settings
import pandas as pd
from strategy import StrategyEngine
from strategy import TrendBias


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class FakeRiskLevels:
    final_stop = 95.0
    final_target = 120.0
    confidence = "ORTA"
    risk_reward_ratio = 2.0
    method_used = "Test"
    position_size = 10
    risk_budget_tl = 200.0
    volatility_scale = 1.0
    atr_pct = 0.02
    correlation_scale = 1.0
    correlated_tickers = []
    blocked_by_correlation = False


class FakeRiskManager:
    def calculate(self, df: pd.DataFrame) -> FakeRiskLevels:
        return FakeRiskLevels()

    def apply_portfolio_risk(self, ticker: str, df: pd.DataFrame, levels: FakeRiskLevels) -> FakeRiskLevels:
        return levels

    def reset_sectors(self) -> None:
        return None

    def reset_portfolio(self) -> None:
        return None

    def check_sector_limit(self, ticker: str) -> bool:
        return True

    def register_position(self, ticker: str, df: pd.DataFrame) -> None:
        return None


class BiasControlledStrategyEngine(StrategyEngine):
    def __init__(self, bias: TrendBias):
        super().__init__(
            indicators=cast(Any, IdentityIndicators()),
            risk_manager=cast(Any, FakeRiskManager()),
        )
        self.bias = bias

    def _get_trend_bias(self, df: pd.DataFrame) -> TrendBias:
        return self.bias


def classify(score: int | float, engine: StrategyEngine) -> str:
    if score >= engine.STRONG_BUY_THRESHOLD:
        return "STRONG_BUY"
    if score >= engine.BUY_THRESHOLD:
        return "BUY"
    if score > max(0, engine.WEAK_BUY_THRESHOLD):
        return "WEAK_BUY"
    if score <= engine.STRONG_SELL_THRESHOLD:
        return "STRONG_SELL"
    if score <= engine.SELL_THRESHOLD:
        return "SELL"
    if score < min(0, engine.WEAK_SELL_THRESHOLD):
        return "WEAK_SELL"
    return "HOLD"


def build_signal_frame() -> pd.DataFrame:
    rows = []
    for idx in range(35):
        rows.append(
            {
                "open": 100.0 + idx,
                "high": 101.0 + idx,
                "low": 99.0 + idx,
                "close": 100.0 + idx,
                "volume": 1000.0,
                "volume_sma_20": 800.0,
                "adx": 28.0,
                "plus_di": 30.0,
                "minus_di": 14.0,
                f"ema_{settings.EMA_LONG}": 90.0,
                "rsi": 24.0,
                "stoch_k": 15.0,
                "stoch_d": 12.0,
                "stoch_cross": "BULLISH",
                "cci": -120.0,
                "sma_cross": "GOLDEN_CROSS",
                "ema_cross": "BULLISH",
                "macd_cross": "BULLISH",
                "macd_histogram": 1.0,
                "macd_hist_increasing": True,
                "di_cross": "BULLISH",
                "bb_position": "BELOW_LOWER",
                "bb_percent": 0.1,
                "bb_squeeze": False,
                "volume_spike": False,
                "volume_ratio": 1.8,
                "price_volume_confirm": True,
                "volume_trend": "INCREASING",
                "obv_trend": "UP",
                "dist_to_support_pct": 1.0,
                "dist_to_resistance_pct": 20.0,
                "rsi_divergence": "NONE",
                "macd_divergence": "NONE",
            }
        )
    return pd.DataFrame(rows)


def test_engine_thresholds_match_config():
    engine = StrategyEngine()

    assert engine.STRONG_BUY_THRESHOLD == settings.STRONG_BUY_THRESHOLD == 48
    assert engine.BUY_THRESHOLD == settings.BUY_THRESHOLD == 20
    assert engine.WEAK_BUY_THRESHOLD == settings.WEAK_BUY_THRESHOLD == 8
    assert engine.WEAK_SELL_THRESHOLD == settings.WEAK_SELL_THRESHOLD == -8
    assert engine.SELL_THRESHOLD == settings.SELL_THRESHOLD == -20
    assert engine.STRONG_SELL_THRESHOLD == settings.STRONG_SELL_THRESHOLD == -48


def test_score_classification_full_range():
    engine = StrategyEngine()
    test_cases = [
        (50, "STRONG_BUY"),
        (48, "STRONG_BUY"),
        (47, "BUY"),
        (20, "BUY"),
        (19, "WEAK_BUY"),
        (8.1, "WEAK_BUY"),
        (8, "HOLD"),
        (7, "HOLD"),
        (0, "HOLD"),
        (-7, "HOLD"),
        (-8, "HOLD"),
        (-8.1, "WEAK_SELL"),
        (-19, "WEAK_SELL"),
        (-20, "SELL"),
        (-47, "SELL"),
        (-48, "STRONG_SELL"),
        (-49, "STRONG_SELL"),
    ]

    for score, expected in test_cases:
        assert classify(score, engine) == expected, f"Score {score}: expected {expected}"


def test_multi_timeframe_long_signal_requires_daily_long_confluence():
    engine = BiasControlledStrategyEngine(TrendBias.SHORT)
    trigger_df = build_signal_frame()
    trend_df = build_signal_frame()

    signal = engine.analyze(
        "TEST.IS",
        {"trend": trend_df, "trigger": trigger_df},
    )

    assert signal is None


def test_multi_timeframe_long_signal_passes_with_daily_long_confluence():
    engine = BiasControlledStrategyEngine(TrendBias.LONG)
    trigger_df = build_signal_frame()
    trend_df = build_signal_frame()

    signal = engine.analyze(
        "TEST.IS",
        {"trend": trend_df, "trigger": trigger_df},
    )

    assert signal is not None
    assert any("MTF confluence" in reason for reason in signal.reasons)
