"""Bit-exact parity for the vectorized divergence / CCI helpers (A1).

The original implementation used ``rolling(...).apply(..., raw=True)``. Those
calls were replaced by vectorized twins in ``TechnicalIndicators``. This module
keeps the pre-change formulas verbatim as a reference oracle and asserts the
new helpers match them exactly (NaN included), so a silent off-by-one in
window alignment or tie-breaking cannot slip through.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bist_bot.indicators import TechnicalIndicators


def _nanargmin(values: np.ndarray) -> float:
    """Original ``TechnicalIndicators._nanargmin`` (kept as oracle)."""
    if np.isnan(values).all():
        return np.nan
    return float(np.nanargmin(values))


def _reference_divergence_args(
    source: pd.Series, lookback: int
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Original rolling.apply pipeline from ``_add_min_divergence``."""
    current_min = source.rolling(window=lookback + 1, min_periods=lookback + 1).min()
    current_argmin = source.rolling(window=lookback + 1, min_periods=lookback + 1).apply(
        _nanargmin,
        raw=True,
    )

    previous_source = source.shift(lookback + 1)
    previous_min = previous_source.rolling(window=lookback, min_periods=1).min()
    previous_argmin = previous_source.rolling(window=lookback, min_periods=1).apply(
        _nanargmin,
        raw=True,
    )
    return current_min, current_argmin, previous_min, previous_argmin


def _make_series(kind: str, n: int, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    if kind == "random":
        values = rng.normal(50.0, 12.0, n)
    elif kind == "ties":
        # Repeated equal minima exercise the first-occurrence tie-break.
        values = np.resize(np.array([5.0, 5.0, 9.0, 5.0, 1.0, 1.0]), n)
    elif kind == "flat":
        values = np.full(n, 42.0)
    elif kind == "nan_leading":
        values = rng.normal(50.0, 12.0, n)
        values[: n // 4] = np.nan
    elif kind == "nan_inner":
        values = rng.normal(50.0, 12.0, n)
        hit = rng.choice(n, size=max(1, n // 5), replace=False)
        values[hit] = np.nan
    elif kind == "nan_trailing":
        values = rng.normal(50.0, 12.0, n)
        values[-(n // 4) :] = np.nan
    else:  # pragma: no cover - guard
        raise AssertionError(kind)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.Series(values, index=idx, dtype=float)


@pytest.mark.parametrize("seed", [0, 7, 99])
@pytest.mark.parametrize("lookback", [3, 5, 7])
@pytest.mark.parametrize(
    "kind", ["random", "ties", "flat", "nan_leading", "nan_inner", "nan_trailing"]
)
def test_rolling_nanargmin_matches_original_apply(kind: str, lookback: int, seed: int) -> None:
    source = _make_series(kind, 160, seed)
    current_min, current_argmin, previous_min, previous_argmin = _reference_divergence_args(
        source, lookback
    )

    new_current = TechnicalIndicators._rolling_nanargmin(
        source.to_numpy(dtype=float), lookback + 1, lookback + 1
    )
    previous_source = source.shift(lookback + 1)
    new_previous = TechnicalIndicators._rolling_nanargmin(
        previous_source.to_numpy(dtype=float), lookback, 1
    )

    pd.testing.assert_series_equal(
        pd.Series(new_current, index=source.index),
        current_argmin,
        check_exact=True,
        check_names=False,
    )
    pd.testing.assert_series_equal(
        pd.Series(new_previous, index=previous_source.index),
        previous_argmin,
        check_exact=True,
        check_names=False,
    )
    # Sanity: the rolling.min path was untouched and still agrees on length.
    assert len(current_min) == len(source)
    assert len(previous_min) == len(source)


@pytest.mark.parametrize("period", [14, 20])
@pytest.mark.parametrize(
    "kind", ["random", "ties", "flat", "nan_leading", "nan_inner", "nan_trailing"]
)
def test_rolling_mean_abs_dev_matches_original_apply(kind: str, period: int) -> None:
    n = 160
    close = _make_series(kind, n, seed=3)
    high = close + 1.0
    low = close - 1.0
    typical_price = (high + low + close) / 3

    reference = typical_price.rolling(window=period).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True
    )
    actual = pd.Series(
        TechnicalIndicators._rolling_mean_abs_dev(typical_price.to_numpy(dtype=float), period),
        index=typical_price.index,
    )

    pd.testing.assert_series_equal(actual, reference, check_exact=True, check_names=False)


def test_short_series_all_nan_window() -> None:
    """A series shorter than the window must stay all-NaN, like pandas."""
    values = np.array([1.0, 2.0, 3.0])
    out = TechnicalIndicators._rolling_nanargmin(values, window=10, min_periods=10)
    assert out.shape == (3,)
    assert np.isnan(out).all()

    dev = TechnicalIndicators._rolling_mean_abs_dev(values, window=10)
    assert dev.shape == (3,)
    assert np.isnan(dev).all()


def _reference_add_min_divergence(
    df: pd.DataFrame,
    source_col: str,
    output_col: str,
    lookback: int,
    low_threshold: float,
    high_threshold: float,
) -> pd.DataFrame:
    """Original ``_add_min_divergence`` using ``rolling.apply(_nanargmin)``.

    Verbatim pre-change body, kept as the oracle for the vectorized version.
    """
    df = df.copy()
    df[output_col] = "NONE"

    if len(df) < lookback * 2:
        return df

    source = df[source_col]
    price = df["close"]
    n_rows = len(df)
    row_positions = np.arange(n_rows)

    current_min, current_argmin, previous_min, previous_argmin = _reference_divergence_args(
        source, lookback
    )

    current_positions = row_positions - lookback + current_argmin.to_numpy(dtype=float)
    previous_starts = np.maximum(0, row_positions - (lookback * 2))
    previous_positions = previous_starts + previous_argmin.to_numpy(dtype=float)

    price_values = price.to_numpy(dtype=float)
    current_price = np.full(n_rows, np.nan, dtype=float)
    previous_price = np.full(n_rows, np.nan, dtype=float)

    valid_current_pos = ~np.isnan(current_positions)
    valid_previous_pos = ~np.isnan(previous_positions)

    current_pos_int = current_positions[valid_current_pos].astype(int)
    previous_pos_int = previous_positions[valid_previous_pos].astype(int)
    current_price[valid_current_pos] = price_values[current_pos_int]
    previous_price[valid_previous_pos] = price_values[previous_pos_int]

    bullish = (
        (current_min < low_threshold)
        & (current_min > previous_min)
        & (current_price < previous_price)
    )
    bearish = (
        (current_min > high_threshold)
        & (current_min < previous_min)
        & (current_price > previous_price)
    )

    eligible_rows = (row_positions >= lookback) & (row_positions < n_rows - 1)
    bullish &= eligible_rows
    bearish &= eligible_rows

    df.loc[bullish, output_col] = "BULLISH"
    df.loc[bearish, output_col] = "BEARISH"
    return df


@pytest.mark.parametrize("lookback", [3, 5, 7])
@pytest.mark.parametrize("kind", ["random", "ties", "flat", "nan_inner", "nan_trailing"])
def test_add_min_divergence_matches_original(kind: str, lookback: int) -> None:
    """Full ``_add_min_divergence`` output must equal the pre-change oracle."""
    n = 200
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    source = _make_series(kind, n, seed=11)

    # Build a realistic RSI-like source plus OHLCV so price lookups are valid.
    df = pd.DataFrame(
        {
            "open": source + 1.0,
            "high": source + 3.0,
            "low": source - 3.0,
            "close": source,
            "volume": np.full(n, 1_000_000.0),
            "rsi": source,
        },
        index=idx,
    )

    expected = _reference_add_min_divergence(df, "rsi", "rsi_divergence", lookback, 35, 65)
    actual = TechnicalIndicators._add_min_divergence(
        df, "rsi", "rsi_divergence", lookback, 35, 65, in_place=False
    )

    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_add_all_produces_divergence_columns() -> None:
    """``add_all`` must emit both divergence columns (it copies the frame)."""
    n = 200
    rng = np.random.default_rng(5)
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    base = 50 + np.cumsum(rng.normal(0, 1.0, n))
    base[::17] = np.nan
    df = pd.DataFrame(
        {
            "open": base + 0.5,
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )

    # add_all returns a new frame (df.copy()); the input must be reassigned.
    out = TechnicalIndicators.add_all(df)
    assert "rsi_divergence" in out.columns
    assert "macd_divergence" in out.columns
    assert set(out["rsi_divergence"].unique()) <= {"NONE", "BULLISH", "BEARISH"}
    assert set(out["macd_divergence"].unique()) <= {"NONE", "BULLISH", "BEARISH"}
    # Input frame untouched (add_all copies).
    assert "rsi_divergence" not in df.columns
