"""Focused tests for Deney B (target_rr wiring) and Deney C (oversold trend confirm).

Deney C contract (P1-B fix, opt-in via ``oversold_requires_trend_confirm``):
- Flag OFF (default): scoring behavior is byte-identical to the legacy path.
- Flag ON: BB BELOW_LOWER and CCI < -100 points are halved unless the bar
  shows bullish trend confirmation (close > SMA20 OR plus_di > minus_di).
  ADX alone never confirms (directionless strength measure).
- Overbought (short-side) branches are never affected by the flag.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.scoring import score_momentum, score_structure
from bist_bot.validation import WalkForwardValidator


def _momentum_row(
    *,
    cci: float | None,
    close: float,
    sma_20: float,
    plus_di: float | None = None,
    minus_di: float | None = None,
) -> pd.Series:
    """Row with only RSI/stoch suppressed so CCI is the sole momentum driver."""
    return pd.Series(
        {
            "rsi": float("nan"),
            "stoch_k": float("nan"),
            "stoch_d": float("nan"),
            "cci": cci,
            "close": close,
            "sma_20": sma_20,
            "plus_di": plus_di,
            "minus_di": minus_di,
        }
    )


def _structure_row(
    *,
    close: float,
    sma_20: float,
    plus_di: float | None = None,
    minus_di: float | None = None,
) -> pd.Series:
    return pd.Series(
        {
            "bb_position": "BELOW_LOWER",
            "bb_percent": float("nan"),
            "bb_squeeze": False,
            "rsi_divergence": "NONE",
            "macd_divergence": "NONE",
            "close": close,
            "sma_20": sma_20,
            "plus_di": plus_di,
            "minus_di": minus_di,
        }
    )


# ----------------------------------------------------------------------
# Deney C — flag off: behavior unchanged
# ----------------------------------------------------------------------
def test_flag_off_default():
    assert StrategyParams().oversold_requires_trend_confirm is False
    assert StrategyParams.conservative().oversold_requires_trend_confirm is False
    assert StrategyParams.research_v1().oversold_requires_trend_confirm is False
    assert StrategyParams().oversold_unconfirmed_score_multiplier == pytest.approx(0.5)


def test_flag_off_bb_full_points():
    params = StrategyParams.conservative()
    # No trend confirmation at all — legacy path must still award full points.
    last = _structure_row(close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(params.score_bollinger_extreme)
    assert reasons == ["Fiyat Bollinger alt bandının altında → Alım fırsatı"]


def test_flag_off_cci_full_points():
    params = StrategyParams.conservative()
    last = _momentum_row(cci=-150.0, close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, reasons = score_momentum(params, last, None)
    assert score == pytest.approx(params.score_cci_extreme)
    assert reasons == ["CCI aşırı satım (-150)"]


# ----------------------------------------------------------------------
# Deney C — flag on, no confirmation: points halved
# ----------------------------------------------------------------------
def test_flag_on_bb_halved_without_confirmation():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    # Bearish directional movement below SMA20 → falling knife → halved.
    last = _structure_row(close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(params.score_bollinger_extreme * 0.5)
    assert "trend onayı yok" in reasons[0]


def test_flag_on_cci_halved_without_confirmation():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    last = _momentum_row(cci=-150.0, close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, _ = score_momentum(params, last, None)
    assert score == pytest.approx(params.score_cci_extreme * 0.5)


def test_flag_on_missing_indicators_counts_as_unconfirmed():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    last = pd.Series({"bb_position": "BELOW_LOWER", "close": 90.0})
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(params.score_bollinger_extreme * 0.5)
    assert "trend onayı yok" in reasons[0]


def test_flag_on_high_adx_alone_does_not_confirm():
    """ADX measures strength, not direction — a strong decline must not confirm."""
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    last = _structure_row(close=90.0, sma_20=100.0, plus_di=10.0, minus_di=40.0)
    last["adx"] = 45.0
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(params.score_bollinger_extreme * 0.5)
    assert "trend onayı yok" in reasons[0]


def test_flag_on_zero_multiplier_removes_points():
    """Measured: 0.5 multiplier never crossed the buy threshold → 0.0 variant."""
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    params.oversold_unconfirmed_score_multiplier = 0.0
    last = _structure_row(close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(0.0)
    assert "trend onayı yok" in reasons[0]


def test_flag_on_zero_multiplier_confirmed_rows_keep_points():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    params.oversold_unconfirmed_score_multiplier = 0.0
    last = _momentum_row(cci=-150.0, close=90.0, sma_20=100.0, plus_di=25.0, minus_di=15.0)
    score, _ = score_momentum(params, last, None)
    assert score == pytest.approx(params.score_cci_extreme)


# ----------------------------------------------------------------------
# Deney C — flag on, confirmation present: full points
# ----------------------------------------------------------------------
def test_flag_on_close_above_sma20_full_points():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    last = _structure_row(close=101.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(params.score_bollinger_extreme)
    assert reasons == ["Fiyat Bollinger alt bandının altında → Alım fırsatı"]


def test_flag_on_bullish_di_confirmation_full_points():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    # close below SMA20 but plus_di > minus_di → bullish directional movement.
    last = _momentum_row(cci=-150.0, close=90.0, sma_20=100.0, plus_di=25.0, minus_di=15.0)
    score, _ = score_momentum(params, last, None)
    assert score == pytest.approx(params.score_cci_extreme)


# ----------------------------------------------------------------------
# Deney C — overbought side untouched
# ----------------------------------------------------------------------
def test_flag_on_overbought_cci_unchanged():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    last = _momentum_row(cci=150.0, close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    score, reasons = score_momentum(params, last, None)
    assert score == pytest.approx(-params.score_cci_extreme)
    assert reasons == ["CCI aşırı alım (150)"]


def test_flag_on_above_upper_bb_unchanged():
    params = StrategyParams.conservative()
    params.oversold_requires_trend_confirm = True
    last = _structure_row(close=90.0, sma_20=100.0, plus_di=15.0, minus_di=30.0)
    last["bb_position"] = "ABOVE_UPPER"
    score, reasons = score_structure(params, last)
    assert score == pytest.approx(-params.score_bollinger_extreme)
    assert reasons == ["Fiyat Bollinger üst bandının üstünde → Aşırı uzamış"]


# ----------------------------------------------------------------------
# Deney B — WalkForwardValidator target_rr wiring
# ----------------------------------------------------------------------
def test_validator_target_rr_default_is_backtester_default():
    wf = WalkForwardValidator()
    assert wf.target_rr is None
    backtester = wf._make_backtester()
    assert backtester.target_rr == pytest.approx(2.0)


def test_validator_target_rr_passed_to_backtester():
    wf = WalkForwardValidator(target_rr=1.2)
    assert wf.target_rr == pytest.approx(1.2)
    backtester = wf._make_backtester()
    assert backtester.target_rr == pytest.approx(1.2)


def test_validator_target_rr_legacy_cost_path():
    wf = WalkForwardValidator(use_cost_model=False, target_rr=1.5)
    backtester = wf._make_backtester()
    assert backtester.target_rr == pytest.approx(1.5)
    assert backtester.cost_model is None


def test_validator_target_rr_invalid():
    with pytest.raises(ValueError, match="target_rr"):
        WalkForwardValidator(target_rr=0.0)
    with pytest.raises(ValueError, match="target_rr"):
        WalkForwardValidator(target_rr=-1.0)


def test_validator_target_rr_ignored_with_factory():
    seen: dict[str, object] = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return object()

    wf = WalkForwardValidator(backtester_factory=factory, target_rr=1.2)
    result = wf._make_backtester()
    assert isinstance(result, object)
    # Factory protocol does not accept target_rr; it must not be forwarded.
    assert "target_rr" not in seen
