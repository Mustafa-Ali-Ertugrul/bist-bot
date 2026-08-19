"""Tests for Monte Carlo simulation module."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_bot.backtest.monte_carlo import (
    MonteCarloResult,
    estimate_gbm_parameters,
    simulate_from_history,
    simulate_geometric_brownian_motion,
    summarize_result,
)


def test_simulate_returns_percentiles() -> None:
    result = simulate_geometric_brownian_motion(mu=0.0, sigma=0.0, n_sims=100, seed=42)
    # Zero drift + zero vol → all paths stay at 1.0 equity, return = 0.
    assert result.percentiles["p50"] == 0.0
    assert result.prob_profit == 0.0  # returns == 0, not strictly > 0


def test_simulate_positive_drift_skews_right() -> None:
    result = simulate_geometric_brownian_motion(mu=0.05, sigma=0.0, n_sims=500, seed=42)
    assert result.percentiles["p50"] > 0.0
    assert result.prob_profit > 0.5


def test_simulate_negative_drift_skews_left() -> None:
    result = simulate_geometric_brownian_motion(mu=-0.05, sigma=0.0, n_sims=500, seed=42)
    assert result.percentiles["p50"] < 0.0
    assert result.prob_profit < 0.5


def test_prob_loss_exceeds_contains_thresholds() -> None:
    result = simulate_geometric_brownian_motion(mu=0.0, sigma=0.02, n_sims=1000, seed=42)
    assert "5%" in result.prob_loss_exceeds
    assert "10%" in result.prob_loss_exceeds


def test_summarize_result_returns_string() -> None:
    result = simulate_geometric_brownian_motion(mu=0.01, sigma=0.01, n_sims=100, seed=1)
    text = summarize_result(result)
    assert isinstance(text, str)
    assert "Olasılıkla kar" in text
    assert "P50" in text


def test_deterministic_with_seed() -> None:
    r1 = simulate_geometric_brownian_motion(seed=123)
    r2 = simulate_geometric_brownian_motion(seed=123)
    assert r1.percentiles == r2.percentiles
    assert r1.prob_profit == r2.prob_profit


def test_estimate_gbm_parameters_defaults_for_missing_data() -> None:
    assert estimate_gbm_parameters(None) == (0.001, 0.02)
    assert estimate_gbm_parameters(pd.DataFrame()) == (0.001, 0.02)


def test_estimate_gbm_parameters_constant_series_is_zero_vol() -> None:
    df = pd.DataFrame({"close": [100.0] * 10})
    mu, sigma = estimate_gbm_parameters(df)
    assert mu == 0.0
    assert sigma == 0.0


def test_simulate_from_history_returns_result() -> None:
    df = pd.DataFrame({"close": np.linspace(100, 120, 60)})
    result = simulate_from_history(df, trials=200, seed=7, horizon_days=30)
    assert isinstance(result, MonteCarloResult)
    assert result.percentiles["p50"] > 0.0
    assert result.prob_profit > 0.5
