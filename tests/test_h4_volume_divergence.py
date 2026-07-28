"""H4 — OBV/volume divergence gate tests for calculate_score_and_reasons.

Verifies that a raw volume spike (vol_confirm +8, vol_spike +8 = +16) cannot
override structural distribution (OBV DOWN / price_volume BEARISH) for a long
candidate. Without this gate, a retail chase while institutions exit produced
the score_engine_audit.md H4 instance (PETKM +54 with "Hacim artıyor" and
"OBV düşüş → çıkış var" co-fired).

Override (min()/max()) only — never a penalty score. H7 saturation owns the
penalty channel.

Symmetric for shorts: OBV UP / price_volume BULLISH caps negative (long-bullish)
short candidates via max(score, -cap).
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pandas as pd  # noqa: E402

from bist_bot.strategy.engine_filters import calculate_score_and_reasons  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402


def _mock_last(obv_trend="FLAT", pv_direction="NONE", close=100.0):
    """Build a minimal last row carrying the OBV / price_volume signals that H4 reads."""
    return pd.Series(
        {
            "close": close,
            "obv_trend": obv_trend,
            "price_volume_direction": pv_direction,
            "adx": 30.0,
        }
    )


def _mock_prev(last):
    """Previous row with a slightly older close."""
    return pd.Series({"close": last["close"] - 0.01})


def _stub_momentum_score_plus50(_last, _prev):
    """Momentum block always contributes +50 (will not be capped by H4)."""
    return 50.0, ["mock momentum"]


def _stub_zero(_last, *_args, **_kwargs):
    return 0.0, []


def _df_two_rows(last, prev):
    return pd.DataFrame([prev.to_dict(), last.to_dict()])


def _run(params, last, prev=None):
    if prev is None:
        prev = _mock_prev(last)
    return calculate_score_and_reasons(
        params,
        ticker="TEST.H4",
        df=_df_two_rows(last, prev),
        last=last,
        prev=prev,
        momentum_scorer=_stub_momentum_score_plus50,
        trend_scorer=_stub_zero,
        volume_scorer=_stub_zero,
        structure_scorer=_stub_zero,
    )


# (a) OBV DOWN + raw score above default cap → cap triggers.
def test_h4_volume_divergence_long_caps_above_cap():
    """OBV DOWN: long score capped at obv_divergence_cap (default 25)."""
    params = StrategyParams(obv_divergence_cap=25.0, obv_divergence_block_enabled=True)
    last = _mock_last(obv_trend="DOWN", pv_direction="NONE", close=110.0)

    result = _run(params, last)

    assert result is not None, "expected a Signal-returnable score (not None)"
    score, reasons, _ = result
    assert score == 25.0, f"OBV DOWN should cap score at 25.0, got {score}"
    assert any("Hacim divergence" in r and "OBV düşüş" in r for r in reasons), (
        f"expected H4 reason added, got: {reasons}"
    )


# (b) OBV UP + bullish price_volume + raw score above cap → gate NOT triggered.
def test_h4_healthy_volume_flow_no_cap():
    """OBV UP + bullish_pv (healthy flow) → gate inert, score untouched."""
    params = StrategyParams(obv_divergence_cap=25.0, obv_divergence_block_enabled=True)
    last = _mock_last(obv_trend="UP", pv_direction="BULLISH_CONFIRMATION", close=110.0)

    result = _run(params, last)

    assert result is not None
    score, reasons, _ = result
    assert score == 50.0, f"healthy flow should keep score unchanged (50), got {score}"
    assert not any("Hacim divergence" in r for r in reasons), (
        f"healthy flow should NOT add H4 reason, got: {reasons}"
    )


# (c) OBV DOWN + raw negative score → symmetric cap applied max(score, -cap).
def test_h4_volume_divergence_short_symmetric_cap():
    """OBV UP / bullish_pv: short score capped via max(score, -cap) symmetric."""
    params = StrategyParams(obv_divergence_cap=25.0, obv_divergence_block_enabled=True)
    last = _mock_last(obv_trend="UP", pv_direction="BULLISH_CONFIRMATION", close=110.0)
    prev = pd.Series({"close": 120.0})  # negative-direction setup below

    def neg_momentum(_last, _prev):
        return -50.0, ["mock momentum"]

    result = calculate_score_and_reasons(
        params,
        ticker="TEST.H4",
        df=_df_two_rows(last, prev),
        last=last,
        prev=prev,
        momentum_scorer=neg_momentum,
        trend_scorer=_stub_zero,
        volume_scorer=_stub_zero,
        structure_scorer=_stub_zero,
    )

    assert result is not None
    score, reasons, _ = result
    assert score == -25.0, f"symmetric cap should raise short to -25.0, got {score}"
    assert any("Hacim divergence" in r and "kısa" in r for r in reasons), (
        f"expected symmetric H4 reason, got: {reasons}"
    )


# (d) obv_divergence_block_enabled=False → kill-switch, old behavior.
def test_h4_divergence_disabled_kill_switch():
    """Kill-switch: enabled=False → no override applied even with OBV DOWN."""
    params = StrategyParams(obv_divergence_cap=25.0, obv_divergence_block_enabled=False)
    last = _mock_last(obv_trend="DOWN", pv_direction="NONE", close=110.0)

    result = _run(params, last)

    assert result is not None
    score, reasons, _ = result
    assert score == 50.0, f"disabled gate should leave score at 50.0, got {score}"
    assert not any("Hacim divergence" in r for r in reasons), (
        f"disabled gate should not add H4 reason, got: {reasons}"
    )


# (e) conservative() cap=15, default cap=25.
def test_h4_conservative_cap_lower_than_default():
    """params.conservative() must use obv_divergence_cap=15 (below buy 25 threshold)."""
    default_params = StrategyParams()
    assert default_params.obv_divergence_cap == 25.0, (
        f"default cap should be 25.0, got {default_params.obv_divergence_cap}"
    )

    if hasattr(StrategyParams, "conservative"):
        cons = StrategyParams.conservative()
        assert cons.obv_divergence_cap == 15.0, (
            f"conservative cap should be 15.0 (below buy_threshold 25), got {cons.obv_divergence_cap}"
        )
        # Sanity: cap(15) < buy_threshold(25) → divergence cannot signal long itself.
        assert cons.obv_divergence_cap < getattr(cons, "buy_threshold", 25.0), (
            "conservative cap must be < buy threshold so gated longs can't buy"
        )


# (f) price_volume BEARISH_CONFIRMATION alone (OBV neutral) → triggers gate.
def test_h4_bearish_pv_alone_triggers_long_cap():
    """price_volume BEARISH_CONFIRMATION alone (OBV=FLAT) → divergence true via bearish_pv."""
    params = StrategyParams(obv_divergence_cap=25.0, obv_divergence_block_enabled=True)
    last = _mock_last(obv_trend="FLAT", pv_direction="BEARISH_CONFIRMATION", close=110.0)

    result = _run(params, last)

    assert result is not None
    score, reasons, _ = result
    assert score == 25.0, f"bearish_pv alone should cap at 25.0, got {score}"
    assert any("Hacim divergence" in r for r in reasons), (
        f"expected H4 reason from bearish_pv, got: {reasons}"
    )


# Conservative-mode scoring integration: cap=15 with full momentum=50 below.
def test_h4_conservative_cap_blocks_buy_signal():
    """conservative cap=15 < momentum=50 means signal capped well below buy_threshold."""
    if not hasattr(StrategyParams, "conservative"):
        return
    params = StrategyParams.conservative()
    params.obv_divergence_block_enabled = True
    last = _mock_last(obv_trend="DOWN", pv_direction="NONE", close=110.0)

    result = _run(params, last)

    assert result is not None
    score, _reasons, _ = result
    assert score == 15.0, f"conservative cap should produce 15.0, got {score}"
    # Below buy threshold (25) means classify_signal will return HOLD, never BUY.
    assert abs(score) < params.buy_threshold, (
        f"|{score}| should be < buy_threshold({params.buy_threshold}) so long can never fire"
    )
