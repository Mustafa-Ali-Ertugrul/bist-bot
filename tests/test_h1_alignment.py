"""H1: Counter-trend directional alignment gating tests.

These tests verify that when the momentum component opposes the dominant
trend direction, the momentum contribution is dampened by
StrategyParams.counter_trend_multiplier before the score is finalized.
"""

from __future__ import annotations

import pytest

from bist_bot.strategy.engine_filters import (
    calculate_score_and_reasons,
    component_direction,
)
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MarketRegime

# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_dataframe(regime: MarketRegime) -> object:
    """Return a minimal DataFrame that detect_regime() identifies as *regime*."""
    import pandas as pd

    rows = []
    for i in range(55):
        if regime is MarketRegime.BULL:
            rows.append(
                {
                    "close": 100.0 + i * 0.5,
                    "adx": 30.0,
                    "plus_di": 25.0,
                    "minus_di": 15.0,
                }
            )
        elif regime is MarketRegime.BEAR:
            rows.append(
                {
                    "close": 100.0 - i * 0.5,
                    "adx": 30.0,
                    "plus_di": 15.0,
                    "minus_di": 25.0,
                }
            )
        else:
            rows.append(
                {
                    "close": 100.0,
                    "adx": 15.0,
                    "plus_di": 20.0,
                    "minus_di": 20.0,
                }
            )
    return pd.DataFrame(rows)


def _scorers(momentum: float, trend: float, volume: float, structure: float):
    """Return four fixed-return scorers and a momentum_checker that always passes."""

    def momentum_scorer(_last, _prev):
        return momentum, ["MR mock"]

    def trend_scorer(_last, _prev, _df=None):
        return trend, ["Trend mock"]

    def volume_scorer(_last, _prev):
        return volume, ["Volume mock"]

    def structure_scorer(_last):
        return structure, ["Structure mock"]

    def momentum_checker(_df, _threshold):
        return True

    return momentum_scorer, trend_scorer, volume_scorer, structure_scorer, momentum_checker


def _run(
    params: StrategyParams, df, momentum: float, trend: float, volume: float, structure: float
):
    """Run calculate_score_and_reasons with fixed component scorers."""
    m_s, t_s, v_s, s_s, mc = _scorers(momentum, trend, volume, structure)
    return calculate_score_and_reasons(
        params,
        "TEST.IS",
        df,
        last=df.iloc[-1],
        prev=df.iloc[-2],
        momentum_scorer=m_s,
        trend_scorer=t_s,
        volume_scorer=v_s,
        structure_scorer=s_s,
        momentum_checker=mc,
    )


# ─── component_direction unit tests ──────────────────────────────────────


class TestComponentDirection:
    def test_positive_score_returns_plus_one(self) -> None:
        assert component_direction(15.0) == 1

    def test_negative_score_returns_minus_one(self) -> None:
        assert component_direction(-10.0) == -1

    def test_zero_score_returns_zero(self) -> None:
        assert component_direction(0.0) == 0


# ─── counter-trend gating: bearish trend, bullish momentum ──────────────


class TestCounterTrendBearishTrendBullishMomentum:
    """Bearish trend (trend_dir=-1) + bullish momentum (momentum_dir=+1)
    → counter-trend gating fires.

    Scenario: price falling but RSI/Stoch/CCI oversold bounce gives
    positive MR contribution. The MR contribution should be dampened.
    """

    def _df(self):
        return _make_dataframe(MarketRegime.BEAR)

    def test_multiplier_zero_nulls_mr_contribution(self) -> None:
        """counter_trend_multiplier=0.0 zeroes out MR contribution entirely."""
        params = StrategyParams(counter_trend_multiplier=0.0)
        # momentum=+20 (counter-trend bullish bounce in bearish trend)
        # trend=-30 (bearish)
        # volume=+5, structure=+15
        # Without gating: 20 + (-30) + 5 + 15 = 10
        # With multiplier=0.0: 0 + (-30) + 5 + 15 = -10
        result = _run(params, self._df(), momentum=20.0, trend=-30.0, volume=5.0, structure=15.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(-10.0)
        assert any("Karşıt-trend bastırma" in r for r in reasons)
        assert "MR mock" in reasons

    def test_multiplier_three_zero_dampens_mr_by_seventy_percent(self) -> None:
        """counter_trend_multiplier=0.3 reduces MR to 30% of original."""
        params = StrategyParams(counter_trend_multiplier=0.3)
        # momentum=+20 → 20 * 0.3 = 6 dampened
        # Without gating: 20 + (-30) + 5 + 15 = 10
        # With multiplier=0.3: 6 + (-30) + 5 + 15 = -4
        result = _run(params, self._df(), momentum=20.0, trend=-30.0, volume=5.0, structure=15.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(-4.0)
        assert any("Karşıt-trend bastırma" in r for r in reasons)

    def test_reason_includes_multiplier_value(self) -> None:
        """The reason string must document the applied multiplier."""
        params = StrategyParams(counter_trend_multiplier=0.3)
        result = _run(params, self._df(), momentum=20.0, trend=-30.0, volume=5.0, structure=15.0)
        _, reasons, _ = result
        reason_text = " ".join(reasons)
        assert "x0.3" in reason_text or "x0,3" in reason_text


# ─── counter-trend gating: bull trend, bearish momentum ─────────────────


class TestCounterTrendBullishTrendBearishMomentum:
    """Bullish trend (trend_dir=+1) + bearish momentum (momentum_dir=-1)
    → counter-trend gating fires (symmetric case).
    """

    def _df(self):
        return _make_dataframe(MarketRegime.BULL)

    def test_multiplier_zero_nulls_mr_contribution_short(self) -> None:
        """Bearish MR contribution fully removed when multiplier=0.0."""
        params = StrategyParams(counter_trend_multiplier=0.0)
        # momentum=-20 (bearish MR in bull trend → counter-trend)
        # trend=+30 (bullish)
        # volume=-5, structure=-15
        # Without gating: (-20) + 30 + (-5) + (-15) = -10
        # With multiplier=0.0: 0 + 30 + (-5) + (-15) = 10
        result = _run(params, self._df(), momentum=-20.0, trend=30.0, volume=-5.0, structure=-15.0)
        assert result is not None
        score, _, _ = result
        assert score == pytest.approx(10.0)

    def test_multiplier_three_dampens_mr_by_seventy_percent_short(self) -> None:
        """counter_trend_multiplier=0.3 dampens bearish MR by 70%."""
        params = StrategyParams(counter_trend_multiplier=0.3)
        # momentum=-20 → -20 * 0.3 = -6 dampened
        # Without gating: (-20) + 30 + (-5) + (-15) = -10
        # With multiplier=0.3: (-6) + 30 + (-5) + (-15) = 4
        result = _run(params, self._df(), momentum=-20.0, trend=30.0, volume=-5.0, structure=-15.0)
        assert result is not None
        score, _, _ = result
        assert score == pytest.approx(4.0)


# ─── gating NOT triggered: aligned directions ────────────────────────────


class TestNoGatingAlignedDirections:
    """When trend and momentum agree, gating must not fire."""

    def test_bull_trend_plus_bull_momentum_no_gating(self) -> None:
        params = StrategyParams(counter_trend_multiplier=0.3)
        df = _make_dataframe(MarketRegime.BULL)
        # All components positive → no gating
        result = _run(params, df, momentum=20.0, trend=30.0, volume=5.0, structure=5.0)
        assert result is not None
        score, _, _ = result
        # 20 + 30 + 5 + 5 = 60, unchanged
        assert score == pytest.approx(60.0)

    def test_bear_trend_plus_bear_momentum_no_gating(self) -> None:
        params = StrategyParams(counter_trend_multiplier=0.3)
        df = _make_dataframe(MarketRegime.BEAR)
        # All components negative → no gating
        result = _run(params, df, momentum=-20.0, trend=-30.0, volume=-5.0, structure=-5.0)
        assert result is not None
        score, _, _ = result
        # (-20) + (-30) + (-5) + (-5) = -60, unchanged
        assert score == pytest.approx(-60.0)


# ─── gating NOT triggered: neutral trend ─────────────────────────────────


class TestNoGatingNeutralTrend:
    """When trend_dir=0, gating must not fire even if momentum opposes."""

    def test_neutral_trend_no_gating(self) -> None:
        params = StrategyParams(counter_trend_multiplier=0.3)
        df = _make_dataframe(MarketRegime.BULL)
        # trend=0 → neutral → no gating regardless of momentum sign
        result = _run(params, df, momentum=20.0, trend=0.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(30.0)  # 20 + 0 + 5 + 5
        assert not any("Karşıt-trend bastırma" in r for r in reasons)


# ─── kill-switch / backward compatibility ────────────────────────────────


class TestKillSwitchMultiplierOne:
    """multiplier=1.0 must reproduce old undamped behaviour (kill-switch)."""

    def test_multiplier_one_equals_legacy_sum(self) -> None:
        params = StrategyParams(counter_trend_multiplier=1.0)
        df = _make_dataframe(MarketRegime.BEAR)
        # counter-trend case: momentum +20, trend -30, volume +5, structure +15
        # With multiplier=1.0: 20*1 + (-30) + 5 + 15 = 10 (same as legacy)
        result = _run(params, df, momentum=20.0, trend=-30.0, volume=5.0, structure=15.0)
        assert result is not None
        score, _, _ = result
        assert score == pytest.approx(10.0)

    def test_multiplier_one_no_gating_when_aligned(self) -> None:
        params = StrategyParams(counter_trend_multiplier=1.0)
        df = _make_dataframe(MarketRegime.BULL)
        # Aligned case: all positive
        result = _run(params, df, momentum=20.0, trend=30.0, volume=5.0, structure=5.0)
        assert result is not None
        score, _, _ = result
        assert score == pytest.approx(60.0)


# ─── conservative profile ────────────────────────────────────────────────


class TestConservativeProfile:
    """conservative() profile sets counter_trend_multiplier=0.0."""

    def test_conservative_multiplier_is_zero(self) -> None:
        params = StrategyParams.conservative()
        assert params.counter_trend_multiplier == 0.0

    def test_default_multiplier_is_point_three(self) -> None:
        params = StrategyParams()
        assert params.counter_trend_multiplier == pytest.approx(0.3)
