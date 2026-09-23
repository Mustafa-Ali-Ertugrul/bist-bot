"""C6 gate: ``validate=True`` and ``validate=False`` must agree on real data.

The scan hot path may skip strict Pydantic candle validation
(``validate=False``) only once this parity holds for well-formed market data —
the class of frames we actually cache. Value parity (OHLCV + timestamps) is
what feeds indicators and therefore signals; cosmetic frame metadata (column
dtypes after ``model_dump``, index *name*) is allowed to differ.

The last test documents the one known divergence: a candle that violates
``high >= low`` makes the strict path reject the WHOLE frame, while the fast
path only drops the bad row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bist_bot.data.schemas import validate_dataframe


def _frame(
    rows: int = 250,
    *,
    columns: str = "upper",
    index_kind: str = "datetime",
    seed: int = 7,
) -> pd.DataFrame:
    """Well-formed OHLCV frame shaped like a provider download."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=rows, freq="D")
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.0, rows))
    high = close + rng.uniform(0.2, 2.0, rows)
    low = close - rng.uniform(0.2, 2.0, rows)
    open_ = (high + low) / 2.0
    data = {
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": rng.integers(1_000, 5_000_000, rows).astype(float),
    }
    if columns == "lower":
        data = {k.lower(): v for k, v in data.items()}
    df = pd.DataFrame(data)
    if index_kind == "datetime":
        df.index = idx
        df.index.name = "Date"
    elif index_kind == "column":
        df = df.reset_index(drop=True)
        df.insert(0, "Date", idx)
    elif index_kind == "naive_index":
        df.index = idx
        df.index.name = None
    return df


def _col(df: pd.DataFrame, name: str) -> str:
    """Column accessor that tolerates provider casing (Open vs open)."""
    if name in df.columns:
        return name
    lowered = name.lower()
    for candidate in df.columns:
        if str(candidate).lower() == lowered:
            return str(candidate)
    raise KeyError(name)


def _with_nan_gap(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.iloc[10, df.columns.get_loc(_col(df, "close"))] = np.nan
    return df


def _with_inf(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.iloc[20, df.columns.get_loc(_col(df, "close"))] = np.inf
    return df


def _with_zero_volume(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.iloc[30, df.columns.get_loc(_col(df, "volume"))] = 0.0
    df.iloc[31, df.columns.get_loc(_col(df, "volume"))] = -5.0
    return df


CASES: dict[str, object] = {
    "datetime_index_upper": lambda: _frame(),
    "lowercase_columns": lambda: _frame(columns="lower"),
    "date_column": lambda: _frame(index_kind="column"),
    "unnamed_index": lambda: _frame(index_kind="naive_index"),
    "nan_gap": lambda: _with_nan_gap(_frame()),
    "inf_value": lambda: _with_inf(_frame()),
    "zero_negative_volume": lambda: _with_zero_volume(_frame()),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_validate_parity_on_well_formed_frames(name: str) -> None:
    """Strict and fast paths return the same candles for cacheable data."""
    source = CASES[name]()  # type: ignore[operator]
    strict = validate_dataframe(source.copy(), validate=True)
    fast = validate_dataframe(source.copy(), validate=False)

    assert (strict is None) == (fast is None), f"{name}: one path rejected the frame"
    if strict is None or fast is None:
        return

    assert list(strict.columns) == list(fast.columns)
    assert strict.index.equals(fast.index)
    # Values are the contract that reaches indicators/signals. Index *name*
    # differs by design (strict renames it to "timestamp") and is cosmetic.
    pd.testing.assert_frame_equal(
        strict[["open", "high", "low", "close", "volume"]],
        fast[["open", "high", "low", "close", "volume"]],
        check_dtype=False,
        check_freq=False,
        check_names=False,
    )


def test_validate_parity_keeps_only_rows_both_paths_agree_on() -> None:
    """A NaN row and a negative-volume row are dropped by BOTH paths."""
    df = _with_zero_volume(_with_nan_gap(_frame(rows=40)))
    strict = validate_dataframe(df.copy(), validate=True)
    fast = validate_dataframe(df.copy(), validate=False)

    assert strict is not None and fast is not None
    assert len(strict) == len(fast) == 38
    pd.testing.assert_frame_equal(
        strict[["open", "high", "low", "close", "volume"]],
        fast[["open", "high", "low", "close", "volume"]],
        check_dtype=False,
        check_freq=False,
        check_names=False,
    )


def test_known_divergence_inverted_candle_rejects_whole_frame() -> None:
    """Documented asymmetry: strict is all-or-nothing, fast drops the bad row.

    ``high < low`` is only detectable by the Pydantic candle validators, so the
    strict path raises and returns ``None`` (ticker skipped entirely) while the
    fast path keeps every row (``_clean_ohlcv`` only drops NaN / non-positive
    OHLCV, not inverted candles). This is the one case where flipping the scan
    hot path to ``validate=False`` changes what gets scanned.
    """
    df = _frame(rows=30)
    col_high = _col(df, "high")
    col_low = _col(df, "low")
    # Invert one candle: high below low.
    df.iloc[5, df.columns.get_loc(col_high)] = 50.0
    df.iloc[5, df.columns.get_loc(col_low)] = 60.0

    strict = validate_dataframe(df.copy(), validate=True)
    fast = validate_dataframe(df.copy(), validate=False)

    assert strict is None
    assert fast is not None
    assert len(fast) == 30
    assert "close" in fast.columns
