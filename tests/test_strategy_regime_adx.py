"""Silent-regression harness for regime detection and ADX soft penalty.

WARNING / UYARI
---------------
If you intentionally change regime thresholds (ADX/DI/momentum cutoffs in
``bist_bot.strategy.regime``), sideways multiplier / buy thresholds in
``StrategyParams``, or ADX soft-penalty size (``adx_low_trend_penalty`` /
``adx_threshold``), you MUST consciously update the expected scores, reject
behavior, and reason-string assertions in this file.

Bu dosya, rejim tespiti ve ADX cezası zeka katmanının eşik değişikliklerinde
sessizce bozulmasını engellemek içindir. Parametreleri bilerek değiştiriyorsanız
aşağıdaki expected değerleri de bilinçli olarak güncelleyin.

Architecture note:
- ``detect_regime`` classifies BULL / BEAR / SIDEWAYS / UNKNOWN.
- ``calculate_score_and_reasons`` applies sideways score damping and optional
  filter, plus momentum confirmation gates.
- ``apply_low_adx_penalty`` is applied by ``StrategyEngine`` *after*
  ``calculate_score_and_reasons`` when ADX is below ``adx_threshold``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bist_bot.strategy.engine_filters import (
    apply_low_adx_penalty,
    calculate_score_and_reasons,
)
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MarketRegime, detect_regime


def _make_regime_frame(
    *,
    n: int = 60,
    close_start: float = 100.0,
    close_end: float = 110.0,
    adx: float = 30.0,
    plus_di: float = 28.0,
    minus_di: float = 12.0,
) -> pd.DataFrame:
    """Build a deterministic OHLCV-lite frame with regime indicator columns."""
    closes = np.linspace(close_start, close_end, n)
    return pd.DataFrame(
        {
            "close": closes,
            "adx": np.full(n, adx, dtype=float),
            "plus_di": np.full(n, plus_di, dtype=float),
            "minus_di": np.full(n, minus_di, dtype=float),
        }
    )


def _bull_trend_frame() -> pd.DataFrame:
    """High ADX, +DI dominant, rising closes → BULL."""
    return _make_regime_frame(
        close_start=100.0,
        close_end=120.0,
        adx=35.0,
        plus_di=28.0,
        minus_di=12.0,
    )


def _bear_trend_frame() -> pd.DataFrame:
    """High ADX, -DI dominant, falling closes → BEAR."""
    return _make_regime_frame(
        close_start=100.0,
        close_end=80.0,
        adx=32.0,
        plus_di=12.0,
        minus_di=28.0,
    )


def _sideways_choppy_frame() -> pd.DataFrame:
    """Low ADX, flat price → SIDEWAYS."""
    return _make_regime_frame(
        close_start=100.0,
        close_end=101.0,
        adx=12.0,
        plus_di=18.0,
        minus_di=17.0,
    )


def _fixed_component_scorers(
    raw_total: float,
) -> tuple[object, object, object, object]:
    """Split a fixed raw total across the four scoring components."""
    m = raw_total * 0.4
    t = raw_total * 0.4
    v = raw_total * 0.1
    s = raw_total * 0.1

    def momentum_scorer(_last: pd.Series, _prev: pd.Series) -> tuple[float, list[str]]:
        return m, ["mock momentum"]

    def trend_scorer(
        _last: pd.Series, _prev: pd.Series, _df=None
    ) -> tuple[float, list[str]]:
        return t, ["mock trend"]

    def volume_scorer(_last: pd.Series, _prev: pd.Series) -> tuple[float, list[str]]:
        return v, ["mock volume"]

    def structure_scorer(_last: pd.Series) -> tuple[float, list[str]]:
        return s, ["mock structure"]

    return momentum_scorer, trend_scorer, volume_scorer, structure_scorer


def _run_score(
    params: StrategyParams,
    df: pd.DataFrame,
    *,
    raw_total: float,
    ticker: str = "TEST.IS",
    momentum_ok: bool = True,
) -> tuple[float, list[str]] | None:
    momentum_scorer, trend_scorer, volume_scorer, structure_scorer = _fixed_component_scorers(
        raw_total
    )
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return calculate_score_and_reasons(
        params,
        ticker,
        df,
        last=last,
        prev=prev,
        momentum_scorer=momentum_scorer,
        trend_scorer=trend_scorer,
        volume_scorer=volume_scorer,
        structure_scorer=structure_scorer,
        momentum_checker=lambda _df, _threshold: momentum_ok,
    )


@pytest.fixture
def params() -> StrategyParams:
    return StrategyParams()


# ---------------------------------------------------------------------------
# Regime detection snapshots
# ---------------------------------------------------------------------------


def test_detect_regime_bull_trend() -> None:
    """Bull Trend: high ADX + positive DI dominance + rising price."""
    df = _bull_trend_frame()
    assert detect_regime(df) is MarketRegime.BULL


def test_detect_regime_bear_trend() -> None:
    """Bear Trend: high ADX + negative DI dominance + falling price."""
    df = _bear_trend_frame()
    assert detect_regime(df) is MarketRegime.BEAR


def test_detect_regime_sideways_choppy() -> None:
    """Sideways/Choppy: low ADX + flat price."""
    df = _sideways_choppy_frame()
    assert detect_regime(df) is MarketRegime.SIDEWAYS


def test_detect_regime_unknown_when_history_too_short() -> None:
    """Frames shorter than 50 bars must remain UNKNOWN (no silent mislabel)."""
    df = _make_regime_frame(n=40, adx=35.0, plus_di=30.0, minus_di=10.0)
    assert detect_regime(df) is MarketRegime.UNKNOWN


# ---------------------------------------------------------------------------
# calculate_score_and_reasons: regime damping + reason labels
# ---------------------------------------------------------------------------


def test_bull_regime_keeps_full_raw_score(params: StrategyParams) -> None:
    """Bull regime must not apply sideways damping."""
    df = _bull_trend_frame()
    result = _run_score(params, df, raw_total=50.0, ticker="BULL.IS")

    assert result is not None
    score, reasons, _ = result
    assert score == pytest.approx(50.0)
    assert "Piyasa rejimi yatay - skor etkisi azaltildi" not in reasons
    assert "mock momentum" in reasons
    assert "mock trend" in reasons


def test_bear_regime_keeps_full_raw_score(params: StrategyParams) -> None:
    """Bear regime must not apply sideways damping on negative scores."""
    df = _bear_trend_frame()
    result = _run_score(params, df, raw_total=-50.0, ticker="BEAR.IS")

    assert result is not None
    score, reasons, _ = result
    assert score == pytest.approx(-50.0)
    assert "Piyasa rejimi yatay - skor etkisi azaltildi" not in reasons


def test_sideways_regime_damps_score_and_labels_reason(params: StrategyParams) -> None:
    """Sideways multiplies score by sideways_score_multiplier and labels reasons."""
    df = _sideways_choppy_frame()
    raw_total = 50.0
    result = _run_score(params, df, raw_total=raw_total, ticker="SIDE.IS")

    assert result is not None
    score, reasons, _ = result
    expected = raw_total * params.sideways_score_multiplier
    assert score == pytest.approx(expected)
    assert expected == pytest.approx(30.0)
    assert "Piyasa rejimi yatay - skor etkisi azaltildi" in reasons
    assert "mock momentum" in reasons
    assert "mock trend" in reasons


def test_sideways_regime_filters_when_damped_score_below_buy_threshold(
    params: StrategyParams,
) -> None:
    """Sideways + weak score must return None (score_filtered_sideways path)."""
    df = _sideways_choppy_frame()
    # 20 * 0.6 = 12.0 which is below default buy_threshold (20)
    result = _run_score(params, df, raw_total=20.0, ticker="SIDE.IS")
    assert result is None


# ---------------------------------------------------------------------------
# ADX soft penalty (engine post-step helper)
# ---------------------------------------------------------------------------


def test_low_adx_applies_soft_penalty_toward_zero(params: StrategyParams) -> None:
    """ADX=15 must pull a positive score toward zero by adx_low_trend_penalty."""
    reasons: list[str] = ["mock trend"]
    score, reasons = apply_low_adx_penalty(params, 15.0, 40.0, reasons)

    assert score == pytest.approx(40.0 - params.adx_low_trend_penalty)
    assert score == pytest.approx(35.0)
    assert any("ADX düşük" in reason for reason in reasons)
    assert any("skor cezası" in reason for reason in reasons)
    assert any("15.0" in reason for reason in reasons)


def test_low_adx_penalty_on_negative_score_moves_toward_zero(
    params: StrategyParams,
) -> None:
    """Negative scores must also move toward zero under low ADX."""
    score, reasons = apply_low_adx_penalty(params, 15.0, -40.0, [])
    assert score == pytest.approx(-40.0 + params.adx_low_trend_penalty)
    assert score == pytest.approx(-35.0)
    assert any("ADX düşük" in reason for reason in reasons)


def test_high_adx_does_not_apply_penalty(params: StrategyParams) -> None:
    """ADX=35 (>= threshold) must leave score and reasons untouched."""
    original_reasons = ["mock trend"]
    score, reasons = apply_low_adx_penalty(params, 35.0, 40.0, list(original_reasons))

    assert score == pytest.approx(40.0)
    assert reasons == original_reasons
    assert not any("ADX düşük" in reason for reason in reasons)


def test_adx_at_threshold_does_not_apply_penalty(params: StrategyParams) -> None:
    """Exactly at adx_threshold is not penalized (soft penalty is strict <)."""
    threshold = float(params.adx_threshold)
    score, reasons = apply_low_adx_penalty(params, threshold, 40.0, [])
    assert score == pytest.approx(40.0)
    assert reasons == []


def test_pipeline_low_adx_after_regime_score(params: StrategyParams) -> None:
    """Mimic engine pipeline: score first, then low-ADX soft penalty.

    Bull frame with artificially low ADX on the last bar still keeps full
    component score from calculate_score_and_reasons, but the post-step
    penalty reduces the final decision score.
    """
    df = _bull_trend_frame()
    # Force last-bar ADX low only for the penalty step (regime uses full frame).
    scored = _run_score(params, df, raw_total=50.0, ticker="BULL.IS")
    assert scored is not None
    base_score, reasons, _ = scored
    assert base_score == pytest.approx(50.0)

    final_score, final_reasons = apply_low_adx_penalty(params, 15.0, base_score, list(reasons))
    assert final_score == pytest.approx(50.0 - params.adx_low_trend_penalty)
    assert final_score == pytest.approx(45.0)
    assert any("ADX düşük" in reason for reason in final_reasons)
    assert "mock trend" in final_reasons


def test_pipeline_high_adx_preserves_regime_score(params: StrategyParams) -> None:
    """High ADX path must not alter the score produced under bull regime."""
    df = _bull_trend_frame()
    scored = _run_score(params, df, raw_total=50.0, ticker="BULL.IS")
    assert scored is not None
    base_score, reasons, _ = scored

    final_score, final_reasons = apply_low_adx_penalty(params, 35.0, base_score, list(reasons))
    assert final_score == pytest.approx(base_score)
    assert final_reasons == reasons
    assert not any("ADX düşük" in reason for reason in final_reasons)


def test_sideways_then_low_adx_stacks_damping_and_penalty(
    params: StrategyParams,
) -> None:
    """Sideways damping (×0.6) then low-ADX penalty must both apply in order."""
    df = _sideways_choppy_frame()
    scored = _run_score(params, df, raw_total=50.0, ticker="SIDE.IS")
    assert scored is not None
    base_score, reasons, _ = scored
    assert base_score == pytest.approx(30.0)
    assert "Piyasa rejimi yatay - skor etkisi azaltildi" in reasons

    final_score, final_reasons = apply_low_adx_penalty(params, 15.0, base_score, list(reasons))
    assert final_score == pytest.approx(30.0 - params.adx_low_trend_penalty)
    assert final_score == pytest.approx(25.0)
    assert "Piyasa rejimi yatay - skor etkisi azaltildi" in final_reasons
    assert any("ADX düşük" in reason for reason in final_reasons)
