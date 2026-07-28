"""H3: Aşırı uzama (chase) blokajı testleri.

Bu testler, fiyatın Bollinger üst bandı dışında, CCI'nın aşırı alım
bölgesinde veya dirence çok yakın olduğu durumlarda chase veto'nun
doğru şekilde tetiklendiğini doğrular. Veto min()/max() override ile
uygulanır (penalty puanı değil), böylece clamp satürasyonunu bypass eder.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bist_bot.strategy.engine_filters import calculate_score_and_reasons
from bist_bot.strategy.params import StrategyParams

# ─── Helpers ──────────────────────────────────────────────────────────────


def _bull_df(last_kwargs: dict | None = None) -> pd.DataFrame:
    """Return a 55-row BULL regime DataFrame.

    The LAST row can be overridden with *last_kwargs* so chase indicators
    can be set independently of the regime signature.
    """
    base = {
        "open": 100.0,
        "high": 100.5,
        "low": 99.5,
        "close": 100.0,
        "adx": 25.0,
        "plus_di": 25.0,
        "minus_di": 15.0,
    }
    rows = []
    for i in range(55):
        row = dict(base)
        row["close"] = 100.0 + i * 0.3  # steadily rising
        rows.append(row)
    df = pd.DataFrame(rows)
    # Override the last row if caller provides extras
    if last_kwargs:
        for k, v in last_kwargs.items():
            df.loc[df.index[-1], k] = v
    return df


def _bear_df(last_kwargs: dict | None = None) -> pd.DataFrame:
    """Return a 55-row BEAR regime DataFrame."""
    base = {
        "open": 100.0,
        "high": 100.5,
        "low": 99.5,
        "close": 100.0,
        "adx": 25.0,
        "plus_di": 15.0,
        "minus_di": 25.0,
    }
    rows = []
    for i in range(55):
        row = dict(base)
        row["close"] = 100.0 - i * 0.3  # steadily falling
        rows.append(row)
    df = pd.DataFrame(rows)
    if last_kwargs:
        for k, v in last_kwargs.items():
            df.loc[df.index[-1], k] = v
    return df


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

    return (
        momentum_scorer,
        trend_scorer,
        volume_scorer,
        structure_scorer,
        momentum_checker,
    )


def _run(params: StrategyParams, df: pd.DataFrame, momentum: float, trend: float, volume: float, structure: float):
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


# ─── Test: (a) chase veto tetiklenir, conservative cap=10 ─────────────


class TestChaseVetoConservative:
    """CCI 198 + BB ABOVE_UPPER + direnç yakın + ADX 20 (zayıf trend)
    + raw score +55 → veto TETİKLENİR, skor 10'a iner."""

    @pytest.fixture
    def df(self):
        return _bull_df(
            {
                "bb_position": "ABOVE_UPPER",
                "cci": 198.0,
                "dist_to_resistance_pct": 0.5,
                "dist_to_support_pct": 15.0,
                "adx": 20.0,  # below strong trend threshold
                "plus_di": 25.0,
                "minus_di": 15.0,
            }
        )

    def test_chase_blocked_to_conservative_cap(self, df):
        """Conservative profile: cap=10 → score clamped to 10."""
        params = StrategyParams.conservative()
        result = _run(params, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(10.0)
        assert any("Aşırı uzama chase koruması" in r for r in reasons)

    def test_chase_blocked_to_default_cap(self, df):
        """Default profile: cap=20 → score clamped to 20."""
        params = StrategyParams()
        result = _run(params, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(20.0)
        assert any("Aşırı uzama chase koruması" in r for r in reasons)


# ─── Test: (b) strong trend ride gevşetir cap ──────────────────────────


class TestChaseVetoWithStrongTrendRide:
    """Aynı chase senaryosu ama ADX 35 + trend=momentum=+1
    → strong_trend_ride tetiklenir, cap=30 uygulanır."""

    @pytest.fixture
    def df(self):
        return _bull_df(
            {
                "bb_position": "ABOVE_UPPER",
                "cci": 198.0,
                "dist_to_resistance_pct": 0.5,
                "dist_to_support_pct": 15.0,
                "adx": 35.0,  # above strong trend threshold
                "plus_di": 25.0,
                "minus_di": 15.0,
            }
        )

    def test_strong_trend_ride_relaxes_cap(self, df):
        """ADX=35 → strong_trend_ride=True → cap=30."""
        params = StrategyParams()
        result = _run(params, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(30.0)
        assert any("Güçlü trend ride" in r for r in reasons)

    def test_strong_trend_ride_conservative_relaxed_cap(self, df):
        """Conservative+ride: cap=20."""
        params = StrategyParams.conservative()
        result = _run(params, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(20.0)
        assert any("Güçlü trend ride" in r for r in reasons)

    def test_strong_trend_ride_requires_trend_momentum_alignment(self, df):
        """ADX 35 ama momentum negatif (bearish MR) → trend_dir=+1, momentum_dir=-1
        → strong_trend_ride=False → sert cap (20) uygulanır."""
        params = StrategyParams()
        result = _run(params, df, momentum=-10.0, trend=20.0, volume=5.0, structure=10.0)
        assert result is not None
        score, reasons, _ = result
        # Raw: -10+20+5+10 = 25, overextended_long True, no ride → cap=20 → min(25,20)=20
        assert score == pytest.approx(20.0)
        assert any("Aşırı uzama chase koruması" in r for r in reasons)
        assert not any("Güçlü trend ride" in r for r in reasons)


# ─── Test: (c) overextended=False, skor değişmez ──────────────────────


class TestNoChaseWhenNotOverextended:
    """BB orta bant + CCI 50 + direnç uzak → overextended=False → skor aynı."""

    @pytest.fixture
    def df(self):
        return _bull_df(
            {
                "bb_position": "MIDDLE",
                "cci": 50.0,
                "dist_to_resistance_pct": 8.0,
                "dist_to_support_pct": 8.0,
                "adx": 30.0,
                "plus_di": 25.0,
                "minus_di": 15.0,
            }
        )

    def test_score_unchanged(self, df):
        params = StrategyParams()
        result = _run(params, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(55.0)
        assert not any("chase" in r.lower() for r in reasons)


# ─── Test: (d) kill-switch: chase_block_enabled=False ──────────────────


class TestChaseKillSwitch:
    """chase_block_enabled=False → blokaj ATLANIR, skor eski düz-toplam ile özdeş."""

    @pytest.fixture
    def df(self):
        return _bull_df(
            {
                "bb_position": "ABOVE_UPPER",
                "cci": 198.0,
                "dist_to_resistance_pct": 0.5,
                "adx": 20.0,
                "plus_di": 25.0,
                "minus_di": 15.0,
            }
        )

    def test_kill_switch_disables_blocking(self, df):
        params = StrategyParams(chase_block_enabled=False)
        result = _run(params, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result is not None
        score, reasons, _ = result
        # Raw 55 > ±100 clamp → score = 55 (within cap), chase block disabled
        assert score == pytest.approx(55.0)
        assert not any("chase" in r.lower() for r in reasons)

    def test_kill_switch_equals_default_behavior_when_chase_off(self, df):
        """Kill-switch ile eski (H3 öncesi) davranış aynı: chase_block_enabled=False."""
        params_off = StrategyParams(chase_block_enabled=False)
        result_off = _run(params_off, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert result_off is not None
        score_off, _, _ = result_off
        assert score_off == pytest.approx(55.0)


# ─── Test: (e) overextended_short, simetrik cap ────────────────────────


class TestChaseVetoShortSide:
    """BB BELOW_LOWER + CCI -198 + destek yakın + ADX 20 + ham skor -55
    → overextended_short tetiklenir, skor -20'e iner (simetrik)."""

    @pytest.fixture
    def df(self):
        return _bear_df(
            {
                "bb_position": "BELOW_LOWER",
                "cci": -198.0,
                "dist_to_support_pct": 0.5,
                "dist_to_resistance_pct": 15.0,
                "adx": 20.0,
                "plus_di": 15.0,
                "minus_di": 25.0,
            }
        )

    def test_short_side_blocked(self, df):
        params = StrategyParams()
        result = _run(params, df, momentum=-25.0, trend=-20.0, volume=-5.0, structure=-5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(-20.0)
        assert any("kısa skor" in r for r in reasons)

    def test_short_side_conservative_tighter_cap(self, df):
        params = StrategyParams.conservative()
        result = _run(params, df, momentum=-25.0, trend=-20.0, volume=-5.0, structure=-5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(-10.0)
        assert any("kısa skor" in r for r in reasons)

    def test_short_side_strong_trend_ride(self, df):
        """ADX 35 + momentum=trend=-1 → strong_trend_ride → cap yumuşar."""
        df = _bear_df(
            {
                "bb_position": "BELOW_LOWER",
                "cci": -198.0,
                "dist_to_support_pct": 0.5,
                "dist_to_resistance_pct": 15.0,
                "adx": 35.0,
                "plus_di": 15.0,
                "minus_di": 25.0,
            }
        )
        params = StrategyParams()
        result = _run(params, df, momentum=-25.0, trend=-20.0, volume=-5.0, structure=-5.0)
        assert result is not None
        score, reasons, _ = result
        assert score == pytest.approx(-30.0)
        assert any("Güçlü trend ride" in r for r in reasons)
        assert any("kısa skor" in r for r in reasons)


# ─── Test: (f) conservative cap=10, default cap=20 ────────────────────


class TestChaseCapValues:
    """Direct assertion on chase cap values for both profiles."""

    def test_conservative_blocked_cap_is_10(self):
        p = StrategyParams.conservative()
        assert p.chase_blocked_score_cap == pytest.approx(10.0)

    def test_conservative_strong_trend_cap_is_20(self):
        p = StrategyParams.conservative()
        assert p.chase_strong_trend_cap == pytest.approx(20.0)

    def test_default_blocked_cap_is_20(self):
        p = StrategyParams()
        assert p.chase_blocked_score_cap == pytest.approx(20.0)

    def test_default_strong_trend_cap_is_30(self):
        p = StrategyParams()
        assert p.chase_strong_trend_cap == pytest.approx(30.0)

    def test_chase_blocked_that_scores_are_different(self):
        """Run same chase scenario with both profiles → conservative=10, default=20."""
        df = _bull_df(
            {
                "bb_position": "ABOVE_UPPER",
                "cci": 198.0,
                "dist_to_resistance_pct": 0.5,
                "adx": 20.0,
                "plus_di": 25.0,
                "minus_di": 15.0,
            }
        )
        cons = StrategyParams.conservative()
        default = StrategyParams()
        r1 = _run(cons, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        r2 = _run(default, df, momentum=25.0, trend=20.0, volume=5.0, structure=5.0)
        assert r1 is not None and r2 is not None
        s1, _, _ = r1
        s2, _, _ = r2
        assert s1 == pytest.approx(10.0)
        assert s2 == pytest.approx(20.0)
        assert s1 != s2  # they must differ
