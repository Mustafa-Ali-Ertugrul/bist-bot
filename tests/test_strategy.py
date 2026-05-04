"""Strategy threshold and signal tests."""

from __future__ import annotations

import os
import sys
from typing import Any, cast
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.risk import RiskLevels  # noqa: E402
from bist_bot.strategy import (  # noqa: E402
    StrategyEngine,
    TrendBias,
)
from bist_bot.strategy.engine_meta import append_signal_reasons, apply_buy_side_risk  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.scoring import score_momentum, score_volume  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class FakeRiskLevels:
    final_stop = 95.0
    final_target = 120.0
    confidence = "confidence.medium"
    risk_reward_ratio = 2.0
    method_used = "Test"
    position_size = 10
    risk_budget_tl = 200.0
    volatility_scale = 1.0
    atr_pct = 0.02
    correlation_scale = 1.0
    correlated_tickers = []
    blocked_by_correlation = False
    signal_probability: float | None = None
    kelly_fraction: float = 0.0
    liquidity_value: float = 0.0


class FakeRiskManager:
    def calculate(self, df: pd.DataFrame) -> FakeRiskLevels:
        return FakeRiskLevels()

    def apply_portfolio_risk(
        self, ticker: str, df: pd.DataFrame, levels: FakeRiskLevels
    ) -> FakeRiskLevels:
        return levels

    def apply_signal_probability(
        self,
        df: pd.DataFrame,
        price: float,
        levels: FakeRiskLevels,
        signal_probability: float,
    ) -> FakeRiskLevels:
        cast(Any, levels).signal_probability = signal_probability
        cast(Any, levels).kelly_fraction = 0.125
        cast(Any, levels).position_size = 6
        cast(Any, levels).liquidity_value = 1500000.0
        return levels

    def reset_sectors(self) -> None:
        return None

    def reset_portfolio(self) -> None:
        return None

    def build_global_correlation_cache(self, data) -> None:
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


class TickerBiasStrategyEngine(BiasControlledStrategyEngine):
    def __init__(self, default_bias: TrendBias, bias_by_ticker: dict[str, TrendBias]):
        super().__init__(default_bias)
        self._bias_by_ticker = bias_by_ticker
        self._active_ticker = ""

    def analyze(self, ticker: str, df, enforce_sector_limit: bool = False):
        self._active_ticker = ticker
        return super().analyze(ticker, df, enforce_sector_limit=enforce_sector_limit)

    def _get_trend_bias(self, df: pd.DataFrame) -> TrendBias:
        return self._bias_by_ticker.get(self._active_ticker, self.bias)


def classify(score: int | float, engine: StrategyEngine) -> str:
    if score >= engine.STRONG_BUY_THRESHOLD:
        return "STRONG_BUY"
    if score >= engine.BUY_THRESHOLD:
        return "BUY"
    if score >= engine.WEAK_BUY_THRESHOLD:
        return "WEAK_BUY"
    if score <= engine.STRONG_SELL_THRESHOLD:
        return "STRONG_SELL"
    if score <= engine.SELL_THRESHOLD:
        return "SELL"
    if score <= engine.WEAK_SELL_THRESHOLD:
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


@pytest.fixture
def bullish_frame() -> pd.DataFrame:
    return build_signal_frame()


@pytest.fixture
def bearish_frame() -> pd.DataFrame:
    df = build_signal_frame()
    df["rsi"] = 78.0
    df["stoch_k"] = 88.0
    df["stoch_d"] = 91.0
    df["stoch_cross"] = "BEARISH"
    df["cci"] = 120.0
    df["sma_cross"] = "DEATH_CROSS"
    df["ema_cross"] = "BEARISH"
    df["macd_cross"] = "BEARISH"
    df["macd_histogram"] = -1.0
    df["macd_hist_increasing"] = False
    df["di_cross"] = "BEARISH"
    df["bb_position"] = "ABOVE_UPPER"
    df["price_volume_confirm"] = False
    df["obv_trend"] = "DOWN"
    df["plus_di"] = 12.0
    df["minus_di"] = 32.0
    return df


def test_engine_thresholds_match_config():
    engine = StrategyEngine()

    assert engine.STRONG_BUY_THRESHOLD == settings.STRONG_BUY_THRESHOLD == 48
    assert engine.BUY_THRESHOLD == settings.BUY_THRESHOLD == 20
    assert engine.WEAK_BUY_THRESHOLD == settings.WEAK_BUY_THRESHOLD == 8
    assert engine.WEAK_SELL_THRESHOLD == settings.WEAK_SELL_THRESHOLD == -8
    assert engine.SELL_THRESHOLD == settings.SELL_THRESHOLD == -20
    assert engine.STRONG_SELL_THRESHOLD == settings.STRONG_SELL_THRESHOLD == -48


def test_engine_uses_configured_sideways_and_momentum_thresholds():
    with settings.override(SIDEWAYS_EXTRA_THRESHOLD=9.0, MOMENTUM_CONFIRMATION_THRESHOLD=6.5):
        engine = StrategyEngine()

    assert engine.SIDEWAYS_EXTRA_THRESHOLD == 9.0
    assert engine.MOMENTUM_CONFIRMATION == 6.5
    assert engine.params.adx_threshold == settings.ADX_THRESHOLD
    assert engine.params.min_trigger_candles == 30
    assert engine.params.sideways_score_multiplier == 0.6


def test_non_buy_signal_does_not_expose_long_trade_plan():
    risk_levels = RiskLevels(
        final_stop=95.0,
        final_target=120.0,
        position_size=10,
        risk_reward_ratio=2.0,
        method_used="Test long plan",
    )

    adjusted = apply_buy_side_risk(
        cast(Any, FakeRiskManager()),
        None,
        "TEST.IS",
        build_signal_frame(),
        signal_type=SignalType.HOLD,
        enforce_sector_limit=False,
        last=pd.Series({"close": 100.0}),
        score=0.0,
        trend_bias=TrendBias.NEUTRAL,
        risk_levels=risk_levels,
    )

    assert adjusted is not None
    assert adjusted.final_stop == 0.0
    assert adjusted.final_target == 0.0
    assert adjusted.position_size == 0

    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.HOLD,
        score=0.0,
        price=100.0,
    )
    append_signal_reasons(signal, adjusted)

    assert signal.reasons == ["Long trade plan not generated: signal is not buy-side"]


def test_volume_price_confirmation_scores_directionally():
    params = StrategyParams()
    base = {
        "volume_sma_20": 1000.0,
        "volume": 1000.0,
        "volume_spike": False,
        "volume_ratio": 1.0,
        "volume_trend": "FLAT",
        "obv_trend": "FLAT",
        "close": 100.0,
        "_prev_close_for_scoring": 99.0,
    }

    bullish_score, bullish_reasons = score_volume(
        params, pd.Series({**base, "price_volume_direction": "BULLISH_CONFIRMATION"})
    )
    bearish_score, bearish_reasons = score_volume(
        params, pd.Series({**base, "price_volume_direction": "BEARISH_CONFIRMATION"})
    )
    pullback_score, pullback_reasons = score_volume(
        params, pd.Series({**base, "price_volume_direction": "LOW_VOLUME_PULLBACK"})
    )

    assert bullish_score == params.score_price_volume_confirm
    assert bullish_reasons == ["Fiyat-Hacim yukselis onayi"]
    assert bearish_score == -params.score_price_volume_confirm
    assert bearish_reasons == ["Fiyat-Hacim dusus onayi"]
    assert pullback_score == 0.0
    assert pullback_reasons == ["Dusuk hacimli geri cekilme"]


def test_rsi_reasons_call_out_extreme_zones_without_reversed_action_wording():
    params = StrategyParams()

    oversold_score, oversold_reasons = score_momentum(
        params, pd.Series({"rsi": 25.0}), pd.Series()
    )
    overbought_score, overbought_reasons = score_momentum(
        params, pd.Series({"rsi": 75.0}), pd.Series()
    )

    assert oversold_score > 0
    assert overbought_score < 0
    assert "Asiri satim" in oversold_reasons[0]
    assert "Asiri alim" in overbought_reasons[0]


def test_engine_uses_configurable_trigger_candle_minimum():
    engine = StrategyEngine(
        indicators=cast(Any, IdentityIndicators()),
        risk_manager=cast(Any, FakeRiskManager()),
        params=StrategyParams(min_trigger_candles=40),
    )
    trigger_df = build_signal_frame()

    assert engine.analyze("TEST.IS", trigger_df) is None


def test_engine_uses_configurable_adx_threshold():
    engine = BiasControlledStrategyEngine(TrendBias.LONG)
    engine.params.adx_threshold = 35.0
    trigger_df = build_signal_frame()

    signal = engine.analyze("TEST.IS", trigger_df)

    assert signal is not None
    assert any("ADX düşük" in r for r in signal.reasons)


def test_engine_filters_when_adx_is_missing():
    engine = BiasControlledStrategyEngine(TrendBias.LONG)
    trigger_df = build_signal_frame()
    trigger_df.loc[:, "adx"] = float("nan")

    signal = engine.analyze("TEST.IS", trigger_df)

    assert signal is None


def test_score_classification_full_range():
    engine = StrategyEngine()
    test_cases = [
        (50, "STRONG_BUY"),
        (48, "STRONG_BUY"),
        (47, "BUY"),
        (20, "BUY"),
        (19, "WEAK_BUY"),
        (8.1, "WEAK_BUY"),
        (8, "WEAK_BUY"),
        (7, "HOLD"),
        (0, "HOLD"),
        (-7, "HOLD"),
        (-8, "WEAK_SELL"),
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


def test_rsi_low_and_macd_bullish_returns_buy_signal(bullish_frame):
    engine = BiasControlledStrategyEngine(TrendBias.LONG)

    signal = engine.analyze("TEST.IS", {"trend": bullish_frame, "trigger": bullish_frame})

    assert signal is not None
    assert signal.signal_type.value in {"🟢 AL", "💰 GÜÇLÜ AL"}


def test_rsi_high_and_macd_bearish_returns_sell_signal(bearish_frame):
    engine = BiasControlledStrategyEngine(TrendBias.SHORT)

    signal = engine.analyze("TEST.IS", {"trend": bearish_frame, "trigger": bearish_frame})

    assert signal is not None
    assert signal.signal_type.value in {"🔴 SAT", "🚨 GÜÇLÜ SAT"}


def test_empty_dataframe_does_not_crash():
    engine = StrategyEngine()

    signal = engine.analyze("TEST.IS", pd.DataFrame())

    assert signal is None


def test_rejection_telemetry_emits_single_event_for_insufficient_history():
    engine = BiasControlledStrategyEngine(TrendBias.LONG)
    short_frame = build_signal_frame().head(10)

    with patch("bist_bot.strategy.engine.logger") as mock_logger:
        signal = engine.analyze("TEST.IS", short_frame)

    assert signal is None
    rejected_calls = [
        call
        for call in mock_logger.info.call_args_list
        if call.args[0] == "strategy_candidate_rejected"
    ]
    assert len(rejected_calls) == 1
    payload = rejected_calls[0].kwargs
    assert payload["ticker"] == "TEST.IS"
    assert payload["reason_code"] == "insufficient_history"
    assert payload["stage"] == "data"
    assert payload["trigger_candle_count"] == 10


def test_rejection_telemetry_emits_single_event_for_portfolio_risk_block(bullish_frame):
    class BlockingRiskManager(FakeRiskManager):
        def apply_portfolio_risk(self, ticker: str, df: pd.DataFrame, levels: FakeRiskLevels):
            levels.position_size = 0
            levels.blocked_by_correlation = True
            levels.liquidity_value = 250000.0
            return levels

    engine = StrategyEngine(
        indicators=cast(Any, IdentityIndicators()),
        risk_manager=cast(Any, BlockingRiskManager()),
    )

    with patch("bist_bot.strategy.engine.logger") as mock_logger:
        signal = engine.analyze("TEST.IS", {"trend": bullish_frame, "trigger": bullish_frame})

    assert signal is None
    rejected_calls = [
        call
        for call in mock_logger.info.call_args_list
        if call.args[0] == "strategy_candidate_rejected"
    ]
    assert len(rejected_calls) == 1
    payload = rejected_calls[0].kwargs
    assert payload["reason_code"] == "portfolio_risk_blocked"
    assert payload["stage"] == "risk"
    assert payload["blocked_by_correlation"] is True
    assert payload["position_size"] == 0


def test_scan_all_emits_rejections_only_for_failed_candidates(bullish_frame):
    engine = TickerBiasStrategyEngine(
        TrendBias.LONG,
        bias_by_ticker={"FAIL_MTF.IS": TrendBias.SHORT},
    )
    short_frame = bullish_frame.head(10)
    data = {
        "PASS.IS": {"trend": bullish_frame, "trigger": bullish_frame},
        "FAIL_MTF.IS": {"trend": bullish_frame, "trigger": bullish_frame},
        "FAIL_SHORT.IS": {"trend": short_frame, "trigger": short_frame},
    }

    with patch("bist_bot.strategy.engine.logger") as mock_logger:
        signals = engine.scan_all(data)

    assert len(signals) == 1
    assert signals[0].ticker == "PASS.IS"
    rejected_calls = [
        call
        for call in mock_logger.info.call_args_list
        if call.args[0] == "strategy_candidate_rejected"
    ]
    assert len(rejected_calls) == 2
    rejected_tickers = {call.kwargs["ticker"] for call in rejected_calls}
    assert rejected_tickers == {"FAIL_MTF.IS", "FAIL_SHORT.IS"}
    assert all(call.kwargs["ticker"] != "PASS.IS" for call in rejected_calls)
    scan_ids = {call.kwargs["scan_id"] for call in rejected_calls}
    assert len(scan_ids) == 1
    summary_calls = [
        call for call in mock_logger.info.call_args_list if call.args[0] == "scan_rejection_summary"
    ]
    assert len(summary_calls) == 1
    summary_payload = summary_calls[0].kwargs
    assert summary_payload["scan_id"] in scan_ids
    assert summary_payload["total_rejections"] == 2
    assert summary_payload["top_reason"] in {"insufficient_history", "confluence_failed"}
    assert summary_payload["top_reason_count"] == 1
    assert summary_payload["top_stage"] in {"data", "confluence"}
    assert summary_payload["top_stage_count"] == 1


def test_scan_all_stores_sorted_rejection_breakdown_and_resets_between_runs(bullish_frame):
    engine = TickerBiasStrategyEngine(
        TrendBias.LONG,
        bias_by_ticker={
            "FAIL_MTF_A.IS": TrendBias.SHORT,
            "FAIL_MTF_B.IS": TrendBias.SHORT,
        },
    )
    short_frame = bullish_frame.head(10)

    first_data = {
        "FAIL_SHORT.IS": {"trend": short_frame, "trigger": short_frame},
        "FAIL_MTF_A.IS": {"trend": bullish_frame, "trigger": bullish_frame},
        "FAIL_MTF_B.IS": {"trend": bullish_frame, "trigger": bullish_frame},
    }
    second_data = {"FAIL_SHORT_ONLY.IS": {"trend": short_frame, "trigger": short_frame}}

    first_signals = engine.scan_all(first_data)
    first_breakdown = engine.get_last_rejection_breakdown()
    second_signals = engine.scan_all(second_data)
    second_breakdown = engine.get_last_rejection_breakdown()

    assert first_signals == []
    assert first_breakdown["total_rejections"] == 3
    assert first_breakdown["by_reason"] == [
        {"reason_code": "confluence_failed", "count": 2},
        {"reason_code": "insufficient_history", "count": 1},
    ]
    assert first_breakdown["by_stage"] == [
        {"stage": "confluence", "count": 2},
        {"stage": "data", "count": 1},
    ]
    assert str(first_breakdown["scan_id"]).startswith("scan-")

    assert second_signals == []
    assert second_breakdown["total_rejections"] == 1
    assert second_breakdown["by_reason"] == [{"reason_code": "insufficient_history", "count": 1}]
    assert second_breakdown["by_stage"] == [{"stage": "data", "count": 1}]
    assert str(second_breakdown["scan_id"]).startswith("scan-")
    assert second_breakdown["scan_id"] != first_breakdown["scan_id"]


def test_scan_rejection_summary_uses_sorted_aggregate_top_values(bullish_frame):
    engine = TickerBiasStrategyEngine(
        TrendBias.LONG,
        bias_by_ticker={
            "FAIL_MTF_A.IS": TrendBias.SHORT,
            "FAIL_MTF_B.IS": TrendBias.SHORT,
        },
    )
    short_frame = bullish_frame.head(10)
    data = {
        "FAIL_SHORT.IS": {"trend": short_frame, "trigger": short_frame},
        "FAIL_MTF_A.IS": {"trend": bullish_frame, "trigger": bullish_frame},
        "FAIL_MTF_B.IS": {"trend": bullish_frame, "trigger": bullish_frame},
    }

    with patch("bist_bot.strategy.engine.logger") as mock_logger:
        signals = engine.scan_all(data)

    assert signals == []
    summary_calls = [
        call for call in mock_logger.info.call_args_list if call.args[0] == "scan_rejection_summary"
    ]
    assert len(summary_calls) == 1
    payload = summary_calls[0].kwargs
    assert payload["total_rejections"] == 3
    assert payload["top_reason"] == "confluence_failed"
    assert payload["top_reason_count"] == 2
    assert payload["top_stage"] == "confluence"
    assert payload["top_stage_count"] == 2


def test_scan_rejection_summary_emits_once_for_zero_rejections(bullish_frame):
    engine = TickerBiasStrategyEngine(TrendBias.LONG, bias_by_ticker={})
    data = {"PASS.IS": {"trend": bullish_frame, "trigger": bullish_frame}}

    with patch("bist_bot.strategy.engine.logger") as mock_logger:
        signals = engine.scan_all(data)

    assert len(signals) == 1
    rejected_calls = [
        call
        for call in mock_logger.info.call_args_list
        if call.args[0] == "strategy_candidate_rejected"
    ]
    assert rejected_calls == []
    summary_calls = [
        call for call in mock_logger.info.call_args_list if call.args[0] == "scan_rejection_summary"
    ]
    assert len(summary_calls) == 1
    payload = summary_calls[0].kwargs
    assert payload["total_rejections"] == 0
    assert payload["top_reason"] == ""
    assert payload["top_reason_count"] == 0
    assert payload["top_stage"] == ""
    assert payload["top_stage_count"] == 0


def test_score_stays_within_expected_bounds(bullish_frame):
    engine = BiasControlledStrategyEngine(TrendBias.LONG)

    signal = engine.analyze("TEST.IS", {"trend": bullish_frame, "trigger": bullish_frame})

    assert signal is not None
    assert -100.0 <= signal.score <= 100.0


def test_analyze_carries_risk_manager_position_size_into_signal(bullish_frame):
    engine = BiasControlledStrategyEngine(TrendBias.LONG)

    signal = engine.analyze("TEST.IS", {"trend": bullish_frame, "trigger": bullish_frame})

    assert signal is not None
    assert signal.position_size == 10


def test_analyze_applies_meta_model_probability_and_kelly(bullish_frame):
    class DummyMetaModel:
        def predict_probability(self, features: dict[str, float]) -> float:
            assert features["score"] > 0
            return 0.64

    class MetaBiasControlledEngine(StrategyEngine):
        def _get_trend_bias(self, df: pd.DataFrame) -> TrendBias:
            return TrendBias.LONG

    engine = MetaBiasControlledEngine(
        indicators=cast(Any, IdentityIndicators()),
        risk_manager=cast(Any, FakeRiskManager()),
        meta_model=DummyMetaModel(),
    )

    signal = engine.analyze("TEST.IS", {"trend": bullish_frame, "trigger": bullish_frame})

    assert signal is not None
    assert signal.signal_probability == 0.64
    assert signal.kelly_fraction == 0.125
    assert signal.position_size == 6
