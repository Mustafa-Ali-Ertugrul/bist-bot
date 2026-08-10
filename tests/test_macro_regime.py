"""Tests for macro regime aggregation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bist_bot.strategy.regime import (
    MACRO_BENCHMARK_TICKERS,
    MarketRegime,
    detect_macro_regime,
    is_macro_bearish,
    is_macro_bullish,
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
