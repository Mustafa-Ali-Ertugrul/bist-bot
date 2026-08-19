"""Monte Carlo simulation for trade outcome distributions.

This module provides lightweight parametric Monte Carlo analysis that can be
used to estimate the probability distribution of portfolio returns under
historical drift/volatility assumptions. It is intentionally simple — no
machine-learning model required.

All public functions default to conservative values so they never degrade
the existing pipeline when called inadvertently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol


class DistributionParams(Protocol):
    """Shape parameters expected by the simulators."""

    @property
    def mean(self) -> float: ...
    @property
    def std(self) -> float: ...
    @property
    def n_simulations(self) -> int: ...
    @property
    def n_steps(self) -> int: ...


@dataclass
class _DefaultParams:
    mean: float = 0.001
    std: float = 0.02
    n_simulations: int = 1_000
    n_steps: int = 20


@dataclass
class MonteCarloResult:
    """Aggregated outcomes from a Monte Carlo run."""

    final_means: list[float] = field(default_factory=list)
    """Per-step mean of terminal equity paths (fractional)."""

    percentiles: dict[str, float] = field(
        default_factory=lambda: {
            "p5": 0.0,
            "p25": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "p95": 0.0,
        }
    )
    """Percentiles of the terminal return distribution."""

    prob_profit: float = 0.5
    """Empirical probability of a positive terminal return."""

    prob_loss_exceeds: dict[str, float] = field(default_factory=dict)
    """P(loss > X %) for a handful of thresholds."""


def _gaussian_quantile(p: float) -> float:
    """Approximate inverse normal CDF (Abramowitz & Stegun, p < 0.5 negated)."""
    if p <= 0 or p >= 1:
        return float("-inf") if p <= 0 else float("inf")
    if p < 0.5:
        return -_gaussian_quantile(1.0 - p)
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


def simulate_geometric_brownian_motion(
    initial_equity: float = 1.0,
    mu: float = 0.001,
    sigma: float = 0.02,
    n_steps: int = 20,
    n_sims: int = 1_000,
    seed: int | None = None,
) -> MonteCarloResult:
    """Run a geometric Brownian motion Monte Carlo.

    Each step returns ``exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)`` where
    Z ~ N(0,1) and dt=1 by default. Returns the terminal distribution statistics.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    drift = (mu - 0.5 * sigma**2) * n_steps
    diff = sigma * math.sqrt(n_steps)
    # Closed-form terminal log-normal for efficiency.
    terminals = initial_equity * np.exp(drift + diff * rng.standard_normal(n_sims))
    returns = terminals / initial_equity - 1.0  # fractional return vs initial

    pct = sorted(float(r) for r in returns)
    n = len(pct)

    def _pct(i: int) -> float:
        idx = max(0, min(n - 1, int(i * n)))
        return pct[idx]

    result = MonteCarloResult(
        percentiles={
            "p5": _pct(0.05),
            "p25": _pct(0.25),
            "p50": _pct(0.50),
            "p75": _pct(0.75),
            "p95": _pct(0.95),
        },
        prob_profit=float(np.mean(returns > 0)),
    )

    # Loss exceedance probabilities.
    thresholds = [-0.05, -0.10, -0.20, -0.30]
    result.prob_loss_exceeds = {f"{abs(t):.0%}": float(np.mean(returns <= t)) for t in thresholds}
    return result


def summarize_result(result: MonteCarloResult) -> str:
    """Return a human-readable one-page summary."""
    lines = [
        "Simülasyon özeti",
        f"  Olasılıkla kar: {result.prob_profit:.1%}",
        "  Dağılım yüzdelikleri (son dönem getiri):",
        f"    P5 : {result.percentiles['p5']:+.2%}",
        f"    P25: {result.percentiles['p25']:+.2%}",
        f"    P50: {result.percentiles['p50']:+.2%}",
        f"    P75: {result.percentiles['p75']:+.2%}",
        f"    P95: {result.percentiles['p95']:+.2%}",
        "  Büyük kayıp olasılıkları:",
    ]
    for thresh, prob in sorted(result.prob_loss_exceeds.items()):
        lines.append(f"    >= {thresh} kayıp: {prob:.1%}")
    return "\n".join(lines)


def estimate_gbm_parameters(df, price_col: str = "close") -> tuple[float, float]:
    """Estimate daily log-return mean/std for GBM from a historical price series.

    Returns the conservative default pair ``(0.001, 0.02)`` when the series is
    missing, too short, or degenerate.
    """
    import numpy as np

    if df is None or price_col not in df.columns:
        return 0.001, 0.02
    prices = df[price_col].astype(float).dropna()
    if len(prices) < 2:
        return 0.001, 0.02
    log_returns = np.log(prices / prices.shift(1)).dropna()
    if len(log_returns) < 1:
        return 0.001, 0.02
    return float(log_returns.mean()), float(log_returns.std())


def simulate_from_history(
    df,
    *,
    trials: int = 1_000,
    seed: int | None = None,
    horizon_days: int = 252,
) -> MonteCarloResult:
    """Run a GBM Monte Carlo using parameters estimated from a price series."""
    mu, sigma = estimate_gbm_parameters(df)
    return simulate_geometric_brownian_motion(
        mu=mu,
        sigma=sigma,
        n_steps=horizon_days,
        n_sims=trials,
        seed=seed,
    )
