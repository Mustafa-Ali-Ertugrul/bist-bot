"""Silent-regression harness for strategy scoring weights and thresholds.

WARNING / UYARI
---------------
If you intentionally change strategy scoring weights, thresholds, or caps in
``bist_bot.strategy.params.StrategyParams`` or ``bist_bot.strategy.scoring``,
you MUST consciously update the expected values / ranking snapshots in this
file. A failing test here usually means a silent ranking/score regression, not
just a syntax or smoke-test failure.

Bu dosya, skorlama ağırlıkları veya eşikler değiştiğinde "kod çalışıyor ama
sıralama/skor sessizce bozuldu" tipindeki regresyonları yakalamak içindir.
Strateji parametrelerini bilerek değiştiriyorsanız, aşağıdaki expected
değerleri de bilinçli olarak güncelleyin.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.scoring import (
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)


@dataclass(frozen=True)
class ScoringFixture:
    """Fixed synthetic bar snapshot used as a scoring regression oracle."""

    ticker: str
    last: pd.Series
    prev: pd.Series
    expected_momentum: float
    expected_trend: float
    expected_volume: float
    expected_structure: float
    expected_total: float


def _ema_long_key() -> str:
    return f"ema_{settings.EMA_LONG}"


def _sma_fast_key() -> str:
    return f"sma_{settings.SMA_FAST}"


def _sma_slow_key() -> str:
    return f"sma_{settings.SMA_SLOW}"


def _bullish_oversold_high_volume() -> ScoringFixture:
    """Strong long bias: oversold momentum + bullish trend + volume + structure."""
    last = pd.Series(
        {
            "close": 100.0,
            "rsi": 22.0,
            "stoch_k": 15.0,
            "stoch_d": 12.0,
            "stoch_cross": "BULLISH",
            "cci": -120.0,
            "adx": 30.0,
            _ema_long_key(): 95.0,
            "sma_cross": "GOLDEN_CROSS",
            _sma_fast_key(): 102.0,
            _sma_slow_key(): 98.0,
            "ema_cross": "BULLISH",
            "macd_cross": "BULLISH",
            "macd_histogram": 0.5,
            "macd_hist_increasing": True,
            "plus_di": 28.0,
            "minus_di": 15.0,
            "di_cross": "BULLISH",
            "volume": 3000.0,
            "volume_sma_20": 1000.0,
            "volume_spike": True,
            "volume_ratio": 3.0,
            "price_volume_direction": "BULLISH_CONFIRMATION",
            "price_volume_confirm": True,
            "volume_trend": "INCREASING",
            "obv_trend": "UP",
            "bb_position": "BELOW_LOWER",
            "bb_percent": 0.05,
            "bb_squeeze": False,
            "dist_to_support_pct": 1.0,
            "dist_to_resistance_pct": 12.0,
            "rsi_divergence": "BULLISH",
            "macd_divergence": "BULLISH",
        }
    )
    prev = pd.Series({"close": 98.0, _ema_long_key(): 96.0})
    return ScoringFixture(
        ticker="BULL.IS",
        last=last,
        prev=prev,
        expected_momentum=43.0,
        expected_trend=63.0,
        expected_volume=24.0,
        expected_structure=43.0,
        expected_total=173.0,
    )


def _bearish_overbought_distribution() -> ScoringFixture:
    """Strong short bias: overbought momentum + bearish trend/structure."""
    last = pd.Series(
        {
            "close": 100.0,
            "rsi": 82.0,
            "stoch_k": 88.0,
            "stoch_d": 90.0,
            "stoch_cross": "BEARISH",
            "cci": 130.0,
            "adx": 32.0,
            _ema_long_key(): 105.0,
            "sma_cross": "DEATH_CROSS",
            _sma_fast_key(): 97.0,
            _sma_slow_key(): 101.0,
            "ema_cross": "BEARISH",
            "macd_cross": "BEARISH",
            "macd_histogram": -0.4,
            "macd_hist_increasing": False,
            "plus_di": 12.0,
            "minus_di": 27.0,
            "di_cross": "BEARISH",
            "volume": 2500.0,
            "volume_sma_20": 1000.0,
            "volume_spike": True,
            "volume_ratio": 2.5,
            "price_volume_direction": "BEARISH_CONFIRMATION",
            "price_volume_confirm": False,
            "volume_trend": "DECREASING",
            "obv_trend": "DOWN",
            "bb_position": "ABOVE_UPPER",
            "bb_percent": 0.95,
            "bb_squeeze": False,
            "dist_to_support_pct": 15.0,
            "dist_to_resistance_pct": 1.0,
            "rsi_divergence": "BEARISH",
            "macd_divergence": "BEARISH",
        }
    )
    prev = pd.Series({"close": 102.0, _ema_long_key(): 104.0})
    return ScoringFixture(
        ticker="BEAR.IS",
        last=last,
        prev=prev,
        expected_momentum=-43.0,
        expected_trend=-58.0,
        expected_volume=-8.0,
        expected_structure=-43.0,
        expected_total=-152.0,
    )


def _neutral_sideways() -> ScoringFixture:
    """Near-flat tape: no strong directional components."""
    last = pd.Series(
        {
            "close": 100.0,
            "rsi": 50.0,
            "stoch_k": 48.0,
            "stoch_d": 50.0,
            "stoch_cross": "NONE",
            "cci": 10.0,
            "adx": 18.0,
            _ema_long_key(): 100.0,
            "sma_cross": "NONE",
            _sma_fast_key(): 100.0,
            _sma_slow_key(): 100.0,
            "ema_cross": "NONE",
            "macd_cross": "NONE",
            "macd_histogram": 0.0,
            "macd_hist_increasing": False,
            "plus_di": 20.0,
            "minus_di": 20.0,
            "di_cross": "NONE",
            "volume": 1000.0,
            "volume_sma_20": 1000.0,
            "volume_spike": False,
            "volume_ratio": 1.0,
            "price_volume_direction": "NONE",
            "price_volume_confirm": False,
            "volume_trend": "FLAT",
            "obv_trend": "FLAT",
            "bb_position": "MIDDLE",
            "bb_percent": 0.5,
            "bb_squeeze": True,
            "dist_to_support_pct": 8.0,
            "dist_to_resistance_pct": 8.0,
            "rsi_divergence": "NONE",
            "macd_divergence": "NONE",
        }
    )
    prev = pd.Series({"close": 100.0, _ema_long_key(): 100.0})
    return ScoringFixture(
        ticker="NEUT.IS",
        last=last,
        prev=prev,
        expected_momentum=0.0,
        expected_trend=-9.0,
        expected_volume=0.0,
        expected_structure=0.0,
        expected_total=-9.0,
    )


def _mixed_mild_bullish() -> ScoringFixture:
    """Mixed setup: mild oversold + moderate trend/volume, no extremes."""
    last = pd.Series(
        {
            "close": 101.0,
            "rsi": 35.0,
            "stoch_k": 40.0,
            "stoch_d": 35.0,
            "stoch_cross": "NONE",
            "cci": -60.0,
            "adx": 22.0,
            _ema_long_key(): 99.0,
            "sma_cross": "NONE",
            _sma_fast_key(): 101.0,
            _sma_slow_key(): 99.0,
            "ema_cross": "NONE",
            "macd_cross": "NONE",
            "macd_histogram": 0.1,
            "macd_hist_increasing": False,
            "plus_di": 22.0,
            "minus_di": 18.0,
            "di_cross": "NONE",
            "volume": 1200.0,
            "volume_sma_20": 1000.0,
            "volume_spike": False,
            "volume_ratio": 1.2,
            "price_volume_direction": "NONE",
            "price_volume_confirm": False,
            "volume_trend": "INCREASING",
            "obv_trend": "UP",
            "bb_position": "MIDDLE",
            "bb_percent": 0.15,
            "bb_squeeze": False,
            "dist_to_support_pct": 3.0,
            "dist_to_resistance_pct": 10.0,
            "rsi_divergence": "NONE",
            "macd_divergence": "NONE",
        }
    )
    prev = pd.Series({"close": 100.0, _ema_long_key(): 99.0})
    return ScoringFixture(
        ticker="MIXD.IS",
        last=last,
        prev=prev,
        expected_momentum=14.0,
        expected_trend=19.0,
        expected_volume=6.0,
        expected_structure=5.0,
        expected_total=44.0,
    )


@pytest.fixture(scope="module")
def scoring_params() -> StrategyParams:
    """Use default StrategyParams so regressions track production defaults."""
    return StrategyParams()


@pytest.fixture(scope="module")
def scoring_universe() -> list[ScoringFixture]:
    """Hardcoded multi-ticker universe covering bull / bear / neutral / mixed."""
    return [
        _bullish_oversold_high_volume(),
        _bearish_overbought_distribution(),
        _neutral_sideways(),
        _mixed_mild_bullish(),
    ]


def _score_fixture(
    params: StrategyParams, fixture: ScoringFixture
) -> dict[str, float]:
    momentum, _ = score_momentum(params, fixture.last, fixture.prev)
    trend, _ = score_trend(params, fixture.last, fixture.prev)
    volume, _ = score_volume(params, fixture.last, fixture.prev)
    structure, _ = score_structure(params, fixture.last)
    return {
        "momentum": float(momentum),
        "trend": float(trend),
        "volume": float(volume),
        "structure": float(structure),
        "total": float(momentum + trend + volume + structure),
    }


@pytest.mark.parametrize(
    "fixture_builder",
    [
        _bullish_oversold_high_volume,
        _bearish_overbought_distribution,
        _neutral_sideways,
        _mixed_mild_bullish,
    ],
    ids=["bullish", "bearish", "neutral", "mixed"],
)
def test_component_score_snapshots_match_expected(
    scoring_params: StrategyParams, fixture_builder
) -> None:
    """Each synthetic ticker must match frozen component + total scores."""
    fixture = fixture_builder()
    scores = _score_fixture(scoring_params, fixture)

    assert scores["momentum"] == pytest.approx(fixture.expected_momentum)
    assert scores["trend"] == pytest.approx(fixture.expected_trend)
    assert scores["volume"] == pytest.approx(fixture.expected_volume)
    assert scores["structure"] == pytest.approx(fixture.expected_structure)
    assert scores["total"] == pytest.approx(fixture.expected_total)


def test_universe_total_score_ranking_is_stable(
    scoring_params: StrategyParams, scoring_universe: list[ScoringFixture]
) -> None:
    """Relative ranking must stay stable when weights/thresholds silently drift."""
    ranked = sorted(
        (
            (fixture.ticker, _score_fixture(scoring_params, fixture)["total"])
            for fixture in scoring_universe
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    assert [ticker for ticker, _ in ranked] == [
        "BULL.IS",
        "MIXD.IS",
        "NEUT.IS",
        "BEAR.IS",
    ]
    totals = {ticker: total for ticker, total in ranked}
    assert totals["BULL.IS"] == pytest.approx(173.0)
    assert totals["MIXD.IS"] == pytest.approx(44.0)
    assert totals["NEUT.IS"] == pytest.approx(-9.0)
    assert totals["BEAR.IS"] == pytest.approx(-152.0)
    assert totals["BULL.IS"] > totals["MIXD.IS"] > totals["NEUT.IS"] > totals["BEAR.IS"]


def test_score_caps_still_bound_extreme_profiles(
    scoring_params: StrategyParams, scoring_universe: list[ScoringFixture]
) -> None:
    """Extreme fixtures must remain inside documented component caps."""
    for fixture in scoring_universe:
        scores = _score_fixture(scoring_params, fixture)
        assert -45.0 <= scores["momentum"] <= 45.0
        assert -70.0 <= scores["trend"] <= 70.0
        assert -26.0 <= scores["volume"] <= 26.0
        assert -50.0 <= scores["structure"] <= 50.0
