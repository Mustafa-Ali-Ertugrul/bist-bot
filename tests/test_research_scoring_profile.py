"""Focused tests for additive research_v1 scoring profile."""

from __future__ import annotations

import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.strategy.engine import StrategyEngine
from bist_bot.strategy.engine_filters import calculate_score_and_reasons
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MarketRegime
from bist_bot.strategy.scoring import (
    MOMENTUM_SCORE_CAP,
    STRUCTURE_SCORE_CAP,
    TREND_SCORE_CAP,
    VOLUME_SCORE_CAP,
    combine_component_scores,
)


def test_caps_exposed():
    assert MOMENTUM_SCORE_CAP == 45
    assert TREND_SCORE_CAP == 70
    assert VOLUME_SCORE_CAP == 26
    assert STRUCTURE_SCORE_CAP == 50


def test_params_has_normalized_flag_and_weights():
    p = StrategyParams()
    assert hasattr(p, "normalized_component_scoring")
    assert hasattr(p, "component_weight_momentum")
    assert hasattr(p, "component_weight_trend")
    assert hasattr(p, "component_weight_volume")
    assert hasattr(p, "component_weight_structure")


def test_research_v1_profile_exists_and_weights():
    p = StrategyParams.research_v1()
    assert p.normalized_component_scoring is True
    # weights as per contract
    assert abs(p.component_weight_momentum - 0.15) < 1e-9
    assert abs(p.component_weight_trend - 0.60) < 1e-9
    assert abs(p.component_weight_volume - 0.15) < 1e-9
    assert abs(p.component_weight_structure - 0.10) < 1e-9
    # inherits conservative thresholds/guards
    assert p.buy_threshold == 25.0
    assert p.sell_threshold == -25.0
    assert p.sideways_score_multiplier == 0.4


def test_from_settings_research_v1_wiring():
    with settings.override(STRATEGY_PROFILE="research_v1"):
        p = StrategyParams.from_settings()
    assert p.normalized_component_scoring is True
    assert isinstance(p, StrategyParams)


def test_from_settings_conservative_unchanged():
    with settings.override(STRATEGY_PROFILE="conservative"):
        p = StrategyParams.from_settings()
    assert p.normalized_component_scoring is False
    # default conservative values remain
    assert p.buy_threshold == 25.0


def test_combine_component_scores_legacy_raw():
    params = StrategyParams()
    params.normalized_component_scoring = False
    total, contrib = combine_component_scores(params, momentum=10, trend=20, volume=5, structure=8)
    assert contrib["momentum"] == 10
    assert contrib["trend"] == 20
    assert contrib["volume"] == 5
    assert contrib["structure"] == 8
    assert total == 43


def test_combine_component_scores_research_normalized_positive():
    params = StrategyParams.research_v1()
    # raw scores at caps -> normalized =1 each
    total, contrib = combine_component_scores(
        params,
        momentum=MOMENTUM_SCORE_CAP,
        trend=TREND_SCORE_CAP,
        volume=VOLUME_SCORE_CAP,
        structure=STRUCTURE_SCORE_CAP,
    )
    # normalized contributions sum to 1, scaled to 100
    assert pytest.approx(total, rel=1e-6) == 100.0
    # each contribution proportional to weight
    assert pytest.approx(contrib["momentum"], rel=1e-6) == 15.0
    assert pytest.approx(contrib["trend"], rel=1e-6) == 60.0
    assert pytest.approx(contrib["volume"], rel=1e-6) == 15.0
    assert pytest.approx(contrib["structure"], rel=1e-6) == 10.0


def test_combine_component_scores_research_normalized_negative():
    params = StrategyParams.research_v1()
    total, contrib = combine_component_scores(
        params,
        momentum=-MOMENTUM_SCORE_CAP,
        trend=-TREND_SCORE_CAP,
        volume=-VOLUME_SCORE_CAP,
        structure=-STRUCTURE_SCORE_CAP,
    )
    assert pytest.approx(total, rel=1e-6) == -100.0
    assert pytest.approx(contrib["momentum"], rel=1e-6) == -15.0
    assert pytest.approx(contrib["trend"], rel=1e-6) == -60.0


def test_combine_component_scores_cap_clamping():
    params = StrategyParams.research_v1()
    # beyond caps should clamp to [-1,1]
    total, contrib = combine_component_scores(
        params,
        momentum=1000,  # > cap
        trend=-1000,
        volume=0,
        structure=0,
    )
    # momentum normalized =1, trend = -1
    assert pytest.approx(contrib["momentum"], rel=1e-6) == 15.0
    assert pytest.approx(contrib["trend"], rel=1e-6) == -60.0
    assert pytest.approx(total, rel=1e-6) == -45.0


def test_combine_component_scores_partial_normalized():
    params = StrategyParams.research_v1()
    # half caps
    total, contrib = combine_component_scores(
        params,
        momentum=MOMENTUM_SCORE_CAP / 2,
        trend=TREND_SCORE_CAP / 2,
        volume=VOLUME_SCORE_CAP / 2,
        structure=STRUCTURE_SCORE_CAP / 2,
    )
    assert pytest.approx(total, rel=1e-6) == 50.0
    assert pytest.approx(contrib["momentum"], rel=1e-6) == 7.5


def test_calculate_score_pipeline_uses_research_normalization(monkeypatch):
    params = StrategyParams.research_v1()
    monkeypatch.setattr(
        "bist_bot.strategy.engine_filters.detect_regime",
        lambda _df: MarketRegime.BULL,
    )

    result = calculate_score_and_reasons(
        params,
        "TEST.IS",
        pd.DataFrame({"close": [99.0, 100.0]}),
        last=pd.Series({"close": 100.0}),
        prev=pd.Series({"close": 99.0}),
        momentum_scorer=lambda *_args: (MOMENTUM_SCORE_CAP / 2, []),
        trend_scorer=lambda *_args: (TREND_SCORE_CAP / 2, []),
        volume_scorer=lambda *_args: (VOLUME_SCORE_CAP / 2, []),
        structure_scorer=lambda *_args: (STRUCTURE_SCORE_CAP / 2, []),
        momentum_checker=lambda *_args: True,
    )

    assert result is not None
    score, reasons, agreement = result
    assert score == pytest.approx(50.0)
    assert agreement == pytest.approx(1.0)
    assert "Araştırma profili: bileşen skorları normalize edildi" in reasons


def test_combine_component_scores_zero_weight_error():
    params = StrategyParams.research_v1()
    params.component_weight_momentum = 0
    params.component_weight_trend = 0
    params.component_weight_volume = 0
    params.component_weight_structure = 0
    with pytest.raises(ValueError):
        combine_component_scores(params, momentum=1, trend=1, volume=1, structure=1)


def test_combine_component_scores_negative_weight_error():
    params = StrategyParams.research_v1()
    params.component_weight_structure = -0.1
    with pytest.raises(ValueError, match="non-negative"):
        combine_component_scores(params, momentum=1, trend=1, volume=1, structure=1)


def test_engine_breakdown_legacy_keys():
    engine = StrategyEngine(params=StrategyParams())
    last = pd.Series({"close": 100})
    prev = pd.Series({"close": 99})
    breakdown = engine._build_score_breakdown(last, prev, df=None)
    assert set(breakdown.keys()) == {"momentum", "trend", "volume", "structure"}
    # no adjustments key in legacy
    assert "adjustments" not in breakdown


def test_engine_breakdown_research_mode_contributions_and_adjustments(monkeypatch):
    params = StrategyParams.research_v1()
    engine = StrategyEngine(params=params)

    # monkeypatch scorers to return deterministic raw values
    def fake_momentum(*args, **kwargs):
        return 22.5, []

    def fake_trend(*args, **kwargs):
        return 35.0, []

    def fake_volume(*args, **kwargs):
        return 13.0, []

    def fake_structure(*args, **kwargs):
        return 25.0, []

    monkeypatch.setattr(engine, "_score_momentum", fake_momentum)
    monkeypatch.setattr(engine, "_score_trend", fake_trend)
    monkeypatch.setattr(engine, "_score_volume", fake_volume)
    monkeypatch.setattr(engine, "_score_structure", fake_structure)

    last = pd.Series({"close": 100})
    prev = pd.Series({"close": 99})
    breakdown = engine._build_score_breakdown(last, prev, df=None, final_score=42.0)
    assert breakdown == {
        "momentum": 7.5,
        "trend": 30.0,
        "volume": 7.5,
        "structure": 5.0,
        "adjustments": -8.0,
    }
    assert sum(breakdown.values()) == pytest.approx(42.0)


def test_research_v1_opt_in_no_side_effects():
    # default params remain unchanged
    default = StrategyParams()
    conservative = StrategyParams.conservative()
    assert default.buy_threshold != conservative.buy_threshold
    # research_v1 should be distinct
    research = StrategyParams.research_v1()
    assert research is not conservative
    assert research.normalized_component_scoring is True
    assert conservative.normalized_component_scoring is False
