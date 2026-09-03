"""Tests for macro regime aggregation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bist_bot.strategy.regime import (
    MACRO_BENCHMARK_TICKERS,
    MACRO_REGIME_MIN_BARS,
    MarketRegime,
    aggregate_macro_regime,
    benchmark_regime_series,
    build_macro_regime_series,
    detect_macro_regime,
    detect_regime,
    is_macro_bearish,
    is_macro_bullish,
    load_macro_regime_series,
)


@pytest.fixture()
def bull_df():
    """DF that will read as BULL (strong ADX + plus_DI dominant)."""
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(100, 150, n)
    high = close + np.random.uniform(0.5, 2, n)
    low = close - np.random.uniform(0.5, 2, n)
    open_ = close + np.random.uniform(-1, 1, n)
    volume = np.ones(n) * 1e6
    adx = np.full(n, 25.0)
    plus_di = np.full(n, 30.0)
    minus_di = np.full(n, 10.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
        },
        index=dates,
    )


@pytest.fixture()
def bear_df():
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.linspace(150, 100, n)
    high = close + np.random.uniform(0.5, 2, n)
    low = close - np.random.uniform(0.5, 2, n)
    open_ = close + np.random.uniform(-1, 1, n)
    volume = np.ones(n) * 1e6
    adx = np.full(n, 25.0)
    plus_di = np.full(n, 10.0)
    minus_di = np.full(n, 30.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
        },
        index=dates,
    )


@pytest.fixture()
def sideways_df():
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = np.ones(n) * 100 + np.sin(np.linspace(0, 4 * np.pi, n)) * 2
    high = close + 1.0
    low = close - 1.0
    open_ = close.copy()
    volume = np.ones(n) * 1e6
    adx = np.full(n, 12.0)
    plus_di = np.full(n, 18.0)
    minus_di = np.full(n, 17.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
        },
        index=dates,
    )


def test_empty_input_returns_unknown():
    assert detect_macro_regime({}) == MarketRegime.UNKNOWN


def test_single_ticker_returns_its_regime(bull_df):
    result = detect_macro_regime({"THYAO.IS": bull_df})
    assert result == MarketRegime.BULL


def test_all_bull(bull_df):
    result = detect_macro_regime({t: bull_df for t in MACRO_BENCHMARK_TICKERS})
    assert result == MarketRegime.BULL


def test_all_bear(bear_df):
    result = detect_macro_regime({t: bear_df for t in MACRO_BENCHMARK_TICKERS})
    assert result == MarketRegime.BEAR


def test_majority_bull_picks_bull(bull_df, bear_df):
    """2 bull + 1 bear → BULL wins."""
    dfs = {"THYAO.IS": bull_df, "GARAN.IS": bull_df, "AKBNK.IS": bear_df}
    result = detect_macro_regime(dfs)
    assert result == MarketRegime.BULL


def test_majority_bear_picks_bear(bull_df, bear_df):
    dfs = {"THYAO.IS": bear_df, "GARAN.IS": bear_df, "AKBNK.IS": bull_df}
    result = detect_macro_regime(dfs)
    assert result == MarketRegime.BEAR


def test_tie_breaks_bull_over_sideways(bull_df, sideways_df, bear_df):
    """1 bullish, 1 bearish, 1 sideways → BULL wins by tie-break order."""
    dfs = {
        "THYAO.IS": bull_df,
        "GARAN.IS": sideways_df,
        "AKBNK.IS": bear_df,
    }
    result = detect_macro_regime(dfs)
    assert result == MarketRegime.BULL


def test_is_macro_bullish_true_when_bull(bull_df):
    assert is_macro_bullish({"T": bull_df}) is True


def test_is_macro_bearish_true_when_bear(bear_df):
    assert is_macro_bearish({"T": bear_df}) is True


def test_helpers_false_for_wrong_regime(bull_df, bear_df):
    assert is_macro_bearish({"T": bull_df}) is False
    assert is_macro_bullish({"T": bear_df}) is False


# ---------------------------------------------------------------------------
# Deney D: macro regime series construction
# ---------------------------------------------------------------------------


def _ohlcv_frame(n: int, *, start: str = "2023-01-02", drift: float = 0.0) -> pd.DataFrame:
    dates = pd.date_range(start, periods=n, freq="B")
    rng = np.random.default_rng(42)
    rets = rng.normal(drift, 1.0, n)
    close = 100.0 * np.exp(np.cumsum(rets) / 100.0)
    return pd.DataFrame(
        {
            "open": close * (1 - 0.001),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )


def _three_benchmark_frames(n: int = 260) -> dict[str, pd.DataFrame]:
    return {
        "THYAO.IS": _ohlcv_frame(n, drift=0.05),
        "GARAN.IS": _ohlcv_frame(n, drift=-0.02),
        "AKBNK.IS": _ohlcv_frame(n, drift=0.0),
    }


def test_build_series_missing_benchmark_raises():
    frames = _three_benchmark_frames()
    del frames["AKBNK.IS"]
    with pytest.raises(ValueError, match="missing benchmark"):
        build_macro_regime_series(frames)


def test_build_series_short_benchmark_raises():
    frames = _three_benchmark_frames()
    frames["GARAN.IS"] = _ohlcv_frame(MACRO_REGIME_MIN_BARS - 1)
    with pytest.raises(ValueError, match="GARAN"):
        build_macro_regime_series(frames)


def test_build_series_output_shape_and_types():
    frames = _three_benchmark_frames()
    series = build_macro_regime_series(frames)
    assert isinstance(series, pd.Series)
    assert isinstance(series.index, pd.DatetimeIndex)
    assert series.index.is_monotonic_increasing
    assert series.index.tz is None
    assert set(series.unique()).issubset(set(MarketRegime))
    # Union of the three identical business-day indices == each index.
    assert len(series) == len(frames["THYAO.IS"])


def test_build_series_causality_vectorized_equals_brute_force():
    """Every date's value must depend only on rows <= that date.

    Compares the vectorized series against the brute-force per-date slicing
    of each benchmark through the actual ``detect_regime`` +
    ``aggregate_macro_regime`` path.
    """
    frames = _three_benchmark_frames(n=120)
    series = build_macro_regime_series(frames)

    from bist_bot.indicators import TechnicalIndicators

    indicators = TechnicalIndicators()
    enriched = {t: indicators.add_all(f.copy()) for t, f in frames.items()}

    for date in series.index[::17]:  # sample dates across the full range
        votes: list[MarketRegime] = []
        for ticker in MACRO_BENCHMARK_TICKERS:
            hist = enriched[ticker].loc[:date]
            if len(hist) < MACRO_REGIME_MIN_BARS:
                continue
            votes.append(detect_regime(hist))
        expected = aggregate_macro_regime(votes)
        assert series.loc[date] == expected, f"mismatch at {date}"


def test_build_series_tz_aware_and_duplicates_are_handled():
    frames = _three_benchmark_frames()
    noisy = frames["THYAO.IS"].copy()
    noisy.index = noisy.index.tz_localize("Europe/Istanbul")
    # Inject a duplicate date (keep=last must apply) and a NaN close row.
    dup = noisy.iloc[[-1]].copy()
    dup["close"] = float(noisy["close"].iloc[-1]) * 1.01
    noisy = pd.concat([noisy, dup])
    noisy.iloc[5, noisy.columns.get_loc("close")] = np.nan
    frames["THYAO.IS"] = noisy

    series = build_macro_regime_series(frames)
    assert series.index.tz is None
    assert not series.index.duplicated().any()


def test_build_series_uses_detect_macro_regime_aggregation_rule():
    """Parity: series aggregation == live detect_macro_regime aggregation."""
    frames = _three_benchmark_frames(n=160)
    series = build_macro_regime_series(frames)

    from bist_bot.indicators import TechnicalIndicators

    indicators = TechnicalIndicators()
    date = series.index[-1]
    live_dfs = {}
    for ticker in MACRO_BENCHMARK_TICKERS:
        hist = frames[ticker].copy()
        hist = hist.loc[:date]
        if len(hist) >= MACRO_REGIME_MIN_BARS:
            live_dfs[ticker] = indicators.add_all(hist)
    assert series.loc[date] == detect_macro_regime(live_dfs)


def test_load_macro_regime_series_cache_only_missing_raises(tmp_path):
    with pytest.raises(ValueError, match="benchmark cache missing"):
        load_macro_regime_series(tmp_path)


def test_load_macro_regime_series_from_parquet_cache(tmp_path):
    frames = _three_benchmark_frames()
    for ticker, frame in frames.items():
        safe = ticker.replace(".", "_").replace("/", "_")
        frame.to_parquet(tmp_path / f"{safe}_3y.parquet")
    series = load_macro_regime_series(tmp_path)
    assert len(series) == len(frames["THYAO.IS"])
    assert isinstance(series.iloc[-1], MarketRegime)


def test_benchmark_regime_series_matches_detect_regime_per_row(bull_df, bear_df):
    for frame, expected in ((bull_df, MarketRegime.BULL), (bear_df, MarketRegime.BEAR)):
        series = benchmark_regime_series(frame)
        assert series.iloc[-1] == expected
        valid = series.iloc[MACRO_REGIME_MIN_BARS - 1 :]
        assert (valid == expected).all()
