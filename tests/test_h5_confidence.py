"""H5: Component agreement-based confidence and soft score gate tests.

H5 changes two things:
  (a) confidence is computed from agreement_ratio (not score thresholds)
  (b) low agreement_ratio triggers a soft score cap (agreement_low_cap)
     — BUT the gate is DISABLED by default (overfitting +18pp when enabled).

agreement_ratio = agreeing / 4  (fixed denominator: 4 scorer directions).
Silent (0) components count as "not agreeing" — they are NOT excluded
from the denominator. This aligns with the audit definition (payda=4).

Confidence is INDEPENDENT of agreement_gate_enabled:
  - agreement_gate_enabled=False → score cap is skipped, but confidence
    is STILL computed from agreement_ratio (honest labeling).
"""

from __future__ import annotations

import pandas as pd
import pytest

from bist_bot.strategy.engine_filters import (
    calculate_score_and_reasons,
    classify_signal,
    component_direction,
)
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MarketRegime

# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_dataframe(regime: MarketRegime = MarketRegime.BULL) -> pd.DataFrame:
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
    params: StrategyParams,
    df: pd.DataFrame,
    momentum: float,
    trend: float,
    volume: float,
    structure: float,
):
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


def test_component_direction_signs():
    assert component_direction(15.0) == 1
    assert component_direction(-5.0) == -1
    assert component_direction(0.0) == 0


# ─── (a) classify_signal confidence from agreement_ratio (payda=4) ─────


def test_confidence_high_when_all_aligned():
    """4/4 aligned → agreement_ratio=1.0 → high."""
    params = StrategyParams()
    _, conf = classify_signal(params, score=50.0, agreement_ratio=1.0)
    assert conf == "confidence.high"


def test_confidence_medium_when_half_aligned():
    """2/4 aligned → agreement_ratio=0.5 → medium (threshold is >=, not >).

    H5 düzeltmesi: eski nonzero-payda 2/2=1.0 (high) verirdi;
    yeni payda=4 ile 2/4=0.5 (medium). Bu kırılma BEKLENEN ve İSTENEN.
    """
    params = StrategyParams()
    _, conf = classify_signal(params, score=50.0, agreement_ratio=0.5)
    assert conf == "confidence.medium"


def test_confidence_low_when_one_aligned():
    """1/4 aligned → agreement_ratio=0.25 → low."""
    params = StrategyParams()
    _, conf = classify_signal(params, score=50.0, agreement_ratio=0.25)
    assert conf == "confidence.low"


def test_confidence_low_when_zero_aligned():
    """0/4 aligned (all zero) → agreement_ratio=0.0 → low."""
    params = StrategyParams()
    _, conf = classify_signal(params, score=50.0, agreement_ratio=0.0)
    assert conf == "confidence.low"


def test_confidence_does_not_depend_on_score():
    """Same agreement_ratio → same confidence regardless of score magnitude."""
    params = StrategyParams()
    _, conf_low_score = classify_signal(params, score=15.0, agreement_ratio=0.75)
    _, conf_high_score = classify_signal(params, score=85.0, agreement_ratio=0.75)
    assert conf_low_score == conf_high_score == "confidence.high"


def test_confidence_independent_of_gate_state():
    """agreement_gate_enabled=False iken confidence HÂLÂ agreement_ratio'dan.

    Etiket dürüstlüğü kilidi: gate skor cap'ini kapatır ama
    confidence etiketini agreement_ratio'dan hesaplaya devam eder.
    """
    params = StrategyParams(agreement_gate_enabled=False)
    _, conf = classify_signal(params, score=50.0, agreement_ratio=0.25)
    assert conf == "confidence.low"


# ─── (b) Soft score gate — ONLY when agreement_gate_enabled=True ─────────


def test_gate_disabled_by_default_no_cap():
    """Default: agreement_gate_enabled=False → score NOT capped.

    H5 skor gate'i bu evrende edge üretmedi, overfitting'i +18pp şişirdi.
    Uses counter_trend_multiplier=1.0 to isolate H5 (no H1 interference).
    """
    params = StrategyParams(counter_trend_multiplier=1.0)
    df = _make_dataframe(MarketRegime.BULL)
    # momentum=+60, trend=-10, volume=-5, structure=-5 → raw=40
    # dirs: +1,-1,-1,-1 → candidate=+1, agreeing=1, ratio=0.25
    result = _run(params, df, momentum=60.0, trend=-10.0, volume=-5.0, structure=-5.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(0.25)
    assert score == pytest.approx(40.0)  # NOT capped (gate disabled)
    assert not any("Bileşen uyumu düşük" in r for r in reasons)


def test_gate_enabled_triggers_cap():
    """agreement_gate_enabled=True + low agreement → score capped.

    Kill-switch hâlâ çalışır; sadece default kapalı.
    """
    params = StrategyParams(agreement_gate_enabled=True, counter_trend_multiplier=1.0)
    df = _make_dataframe(MarketRegime.BULL)
    # momentum=+60, trend=-10, volume=-5, structure=-5 → raw=40
    # dirs: +1,-1,-1,-1 → candidate=+1, agreeing=1, ratio=0.25
    result = _run(params, df, momentum=60.0, trend=-10.0, volume=-5.0, structure=-5.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(0.25)
    assert score == pytest.approx(30.0)  # capped at agreement_low_cap
    assert any("Bileşen uyumu düşük" in r for r in reasons)


def test_gate_enabled_conservative_cap():
    """Conservative: agreement_low_cap=15 when gate enabled."""
    params = StrategyParams.conservative()
    params.agreement_gate_enabled = True
    params.counter_trend_multiplier = 1.0
    df = _make_dataframe(MarketRegime.BULL)
    # momentum=+60, trend=-10, volume=-5, structure=-5 → raw=40
    result = _run(params, df, momentum=60.0, trend=-10.0, volume=-5.0, structure=-5.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(0.25)
    assert score == pytest.approx(15.0)  # conservative cap
    assert any("Bileşen uyumu düşük" in r for r in reasons)


def test_gate_disabled_confidence_still_from_agreement():
    """Even with gate disabled, classify_signal uses agreement_ratio for confidence."""
    params = StrategyParams(agreement_gate_enabled=False)
    _, conf = classify_signal(params, score=50.0, agreement_ratio=0.25)
    assert conf == "confidence.low"  # still based on agreement, not score


def test_all_aligned_no_score_cap():
    """4/4 aligned → agreement_ratio=1.0 → score NOT capped (even with gate on)."""
    params = StrategyParams(agreement_gate_enabled=True, counter_trend_multiplier=1.0)
    df = _make_dataframe(MarketRegime.BULL)
    # momentum=+30, trend=+20, volume=+10, structure=+10 → raw=70, all +1
    result = _run(params, df, momentum=30.0, trend=20.0, volume=10.0, structure=10.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(1.0)
    assert score == pytest.approx(70.0)  # not capped
    assert not any("Bileşen uyumu düşük" in r for r in reasons)


def test_half_aligned_no_cap_at_threshold():
    """2/4 aligned → agreement_ratio=0.5 == threshold(0.50) → NOT capped (strict <).

    The gate condition is agreement_ratio < agreement_gate_threshold, so
    exactly 0.50 does NOT trigger the cap. This is the boundary behavior.
    """
    params = StrategyParams(agreement_gate_enabled=True, counter_trend_multiplier=1.0)
    df = _make_dataframe(MarketRegime.BULL)
    # momentum=+30, trend=+20, volume=-5, structure=-5 → raw=40
    # dirs: +1,+1,-1,-1 → candidate=+1, agreeing=2, ratio=0.5
    result = _run(params, df, momentum=30.0, trend=20.0, volume=-5.0, structure=-5.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(0.5)
    assert score == pytest.approx(40.0)  # not capped (boundary)
    assert not any("Bileşen uyumu düşük" in r for r in reasons)


def test_cap_applies_to_negative_scores():
    """Low agreement on negative score → score raised to -agreement_low_cap."""
    params = StrategyParams(agreement_gate_enabled=True, counter_trend_multiplier=1.0)
    df = _make_dataframe(MarketRegime.BEAR)
    # momentum=-60, trend=+10, volume=+5, structure=+5 → raw=-40
    # dirs: -1,+1,+1,+1 → candidate=-1, agreeing=1, ratio=0.25
    result = _run(params, df, momentum=-60.0, trend=10.0, volume=5.0, structure=5.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(0.25)
    assert score == pytest.approx(-30.0)  # capped at -agreement_low_cap
    assert any("Bileşen uyumu düşük" in r for r in reasons)


# ─── (c) Edge case: all components zero ───────────────────────────────────


def test_all_zero_components_agreement_zero():
    """All scorers return 0 → nonzero_dirs empty → agreement_ratio=0.0.

    Score=0 → calculate_score_and_reasons returns None (score_zero_after_penalty).
    """
    params = StrategyParams()
    df = _make_dataframe(MarketRegime.BULL)
    result = _run(params, df, momentum=0.0, trend=0.0, volume=0.0, structure=0.0)
    assert result is None


# ─── (d) Signal.agreement_ratio field ─────────────────────────────────────


def test_signal_has_agreement_ratio_field():
    """Signal dataclass must accept and store agreement_ratio."""
    from bist_bot.strategy.signal_models import Signal, SignalType

    sig = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        agreement_ratio=0.5,
    )
    assert sig.agreement_ratio == 0.5


def test_signal_agreement_ratio_defaults_to_none():
    """Signal without agreement_ratio should default to None."""
    from bist_bot.strategy.signal_models import Signal, SignalType

    sig = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
    )
    assert sig.agreement_ratio is None


def test_signal_with_locale_preserves_agreement_ratio():
    """with_locale() must carry agreement_ratio forward."""
    from bist_bot.strategy.signal_models import Signal, SignalType

    sig = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        agreement_ratio=0.75,
    )
    localized = sig.with_locale("tr")
    assert localized.agreement_ratio == 0.75


# ─── (e) Payda=4 senaryosu: 2 aligned + 2 zero → ratio=0.5 (medium) ───────


def test_two_aligned_two_zero_is_medium_not_high():
    """2 aligned + 2 zero → agreement_ratio=0.5 → confidence.medium.

    H5 düzeltmesi: eski nonzero-payda 2/2=1.0 (high) verirdi;
    yeni payda=4 ile 2/4=0.5 (medium). Bu kırılma BEKLENEN ve İSTENEN.
    """
    params = StrategyParams()
    df = _make_dataframe(MarketRegime.BULL)
    # momentum=+30, trend=+20, volume=0, structure=0 → raw=50
    # dirs: +1,+1,0,0 → candidate=+1, agreeing=2, ratio=2/4=0.5
    result = _run(params, df, momentum=30.0, trend=20.0, volume=0.0, structure=0.0)
    assert result is not None
    score, reasons, agreement = result
    assert agreement == pytest.approx(0.5)
    assert score == pytest.approx(50.0)  # gate disabled, no cap
    # Confidence from agreement_ratio (payda=4)
    _, conf = classify_signal(params, score=50.0, agreement_ratio=agreement)
    assert conf == "confidence.medium"
