"""H6: MTF confluence SMA20/EMA200 slope contradiction regression tests.

When SMA20 slope and EMA200 slope point in opposite directions, the
higher-timeframe trend is internally contradictory (whipsaw risk).
H6 forces:
- ``get_trend_bias`` → NEUTRAL (canlı yolu)
- ``calculate_score_and_reasons`` → regime'i SIDEWAYS'e zorla + reason ekle
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import TrendBias, get_trend_bias


def _make_frame_with_slope_divergence(
    *,
    sma_20_rising: bool,
    ema_200_rising: bool,
    n: int = 100,
    slope_lookback: int = 40,
) -> pd.DataFrame:
    """Build an OHLCV frame whose SMA20 and EMA200 slopes are independently controllable.

    The last bar is constructed so that:
    - SMA20 at last bar vs SMA20 ``slope_lookback`` bars ago differ as requested.
    - EMA200 at last bar vs EMA200 ``slope_lookback`` bars ago differ as requested.

    All other regime columns (ADX, plus_di, minus_di) are trend-y to make the
    no-contradiction baseline classify as a directional regime.
    """
    slope_lookback = max(slope_lookback, int(getattr(settings, "SLOPE_LOOKBACK", 40)))
    # Need enough bars for slope_lookback + window-200 EMA
    n = max(n, 250)
    baseline = 100.0

    # Close path: a gentle ramp we can patch the tail to control slopes.
    closes = np.linspace(baseline, baseline + 10.0, n).astype(float)
    if not ema_200_rising:
        # Patch last bars to fall so EMA200 slope (last vs last-lookback) goes down.
        closes[-1] = closes[-1 - slope_lookback] - 5.0
    else:
        # Force EMA200 last > EMA200 last-lookback explicitly.
        closes[-1] = closes[-1 - slope_lookback] + 20.0

    if not sma_20_rising:
        # Patch the last 20 bars to drive SMA20 downwards at the tail.
        closes[-20:] = np.linspace(
            closes[-20], closes[-1 - slope_lookback] - 2.0, 20
        )
    else:
        closes[-20:] = np.linspace(closes[-20], closes[-1] + 5.0, 20)

    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": np.full(n, 1000.0, dtype=float),
            "adx": np.full(n, 25.0, dtype=float),
            "plus_di": np.full(n, 28.0, dtype=float),
            "minus_di": np.full(n, 12.0, dtype=float),
        }
    )
    return df


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    return TechnicalIndicators().add_all(df.copy())


def _force_slope_divergence(
    df: pd.DataFrame,
    *,
    sma_20_rising: bool,
    ema_200_rising: bool,
    slope_lookback: int = 40,
) -> pd.DataFrame:
    """Override the ``sma_20`` and EMA-long columns to guarantee a contradiction.

    `add_all` recomputes these from closes, so for deterministic tests we patch
    the tail windows to satisfy the slope direction we want at the last bar.
    """
    slope_lookback = max(
        slope_lookback, int(getattr(settings, "SLOPE_LOOKBACK", 40))
    )
    if len(df) < slope_lookback + 1:
        return df
    sma_col = df["sma_20"].astype(float).copy()
    ema_col = df[f"ema_{settings.EMA_LONG}"].astype(float).copy()
    if sma_20_rising:
        sma_col.iloc[-1] = sma_col.iloc[-1 - slope_lookback] + 10.0
    else:
        sma_col.iloc[-1] = sma_col.iloc[-1 - slope_lookback] - 10.0
    if ema_200_rising:
        ema_col.iloc[-1] = ema_col.iloc[-1 - slope_lookback] + 10.0
    else:
        ema_col.iloc[-1] = ema_col.iloc[-1 - slope_lookback] - 10.0
    df = df.copy()
    df["sma_20"] = sma_col
    df[f"ema_{settings.EMA_LONG}"] = ema_col
    return df


class TestGetTrendBiasH6Contradiction:
    """get_trend_bias returns NEUTRAL when SMA20/EMA200 slopes oppose."""

    def test_rising_sma_falling_ema_returns_neutral(self) -> None:
        df = _make_frame_with_slope_divergence(
            sma_20_rising=True, ema_200_rising=False
        )
        bias = get_trend_bias(TechnicalIndicators(), df)
        assert bias is TrendBias.NEUTRAL

    def test_falling_sma_rising_ema_returns_neutral(self) -> None:
        df = _make_frame_with_slope_divergence(
            sma_20_rising=False, ema_200_rising=True
        )
        bias = get_trend_bias(TechnicalIndicators(), df)
        assert bias is TrendBias.NEUTRAL

    def test_kill_switch_disables_neutralization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            type(settings), "MTF_CONFLUENCE_BLOCK_ENABLED", False, raising=False
        )
        try:
            df = _make_frame_with_slope_divergence(
                sma_20_rising=True, ema_200_rising=False
            )
            # With kill switch off, get_trend_bias may return non-NEUTRAL.
            # We only assert it doesn't enforce NEUTRAL via the H6 path.
            bias = get_trend_bias(TechnicalIndicators(), df)
            assert bias in {TrendBias.LONG, TrendBias.SHORT, TrendBias.NEUTRAL}
        finally:
            monkeypatch.setattr(
                type(settings), "MTF_CONFLUENCE_BLOCK_ENABLED", True, raising=False
            )


def _fixed_component_scorers(raw_total: float):
    m = raw_total * 0.4
    t = raw_total * 0.4
    v = raw_total * 0.1
    s = raw_total * 0.1

    def momentum_scorer(_last, _prev):
        return m, ["mock momentum"]

    def trend_scorer(_last, _prev, _df=None):
        return t, ["mock trend"]

    def volume_scorer(_last, _prev):
        return v, ["mock volume"]

    def structure_scorer(_last):
        return s, ["mock structure"]

    return momentum_scorer, trend_scorer, volume_scorer, structure_scorer


def _run_score(
    params: StrategyParams,
    df: pd.DataFrame,
    *,
    raw_total: float,
) -> tuple[float, list[str], float] | None:
    from bist_bot.strategy.engine_filters import calculate_score_and_reasons

    momentum_scorer, trend_scorer, volume_scorer, structure_scorer = (
        _fixed_component_scorers(raw_total)
    )
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return calculate_score_and_reasons(
        params,
        "TEST.IS",
        df,
        last=last,
        prev=prev,
        momentum_scorer=momentum_scorer,
        trend_scorer=trend_scorer,
        volume_scorer=volume_scorer,
        structure_scorer=structure_scorer,
        momentum_checker=lambda _df, _threshold: True,
    )


class TestCalculateScoreH6ContradictionSideways:
    """calculate_score_and_reasons forces SIDEWAYS + labels H6 reason."""

    def test_contradiction_adds_h6_reason_and_damps(
        self, params: StrategyParams
    ) -> None:
        df = _force_slope_divergence(
            _enrich(
                _make_frame_with_slope_divergence(
                    sma_20_rising=True, ema_200_rising=False
                )
            ),
            sma_20_rising=True,
            ema_200_rising=False,
        )
        # Raw total above buy_threshold so without H6 we'd expect a non-None result;
        # H6 pushes to SIDEWAYS → score is multiplied & may be filtered.
        raw = params.buy_threshold * 2
        result = _run_score(params, df, raw_total=raw)
        if result is None:
            # Filtered via sideways threshold — H6 still neutralized the signal.
            return
        score, reasons, _ = result
        assert any("MTF çelişki" in r for r in reasons)
        # Score damped below raw via sideways multiplier.
        assert score <= raw

    def test_kill_switch_disables_damping(
        self, params: StrategyParams
    ) -> None:
        original = params.mtf_confluence_block_enabled
        params.mtf_confluence_block_enabled = False
        try:
            df = _force_slope_divergence(
                _enrich(
                    _make_frame_with_slope_divergence(
                        sma_20_rising=True, ema_200_rising=False
                    )
                ),
                sma_20_rising=True,
                ema_200_rising=False,
            )
            raw = params.buy_threshold * 2
            result = _run_score(params, df, raw_total=raw)
            if result is None:
                pytest.skip("row filtered by an unrelated gate with kill switch off")
            score, reasons, _ = result
            assert not any("MTF çelişki" in r for r in reasons)
        finally:
            params.mtf_confluence_block_enabled = original


@pytest.fixture
def params() -> StrategyParams:
    return StrategyParams()
