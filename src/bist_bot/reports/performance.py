"""Paper-trade performance metrics engine (pure stdlib, no DB/settings imports).

Sprint 1: powers the daily-report "Performans Özeti (Paper Trading)" section.
All headline statistics cover only *actionable* closed trades (score >= 25);
RADAR (20-25) trades stay a separate calibration population.

Rules:
- n < MIN_SAMPLE: no confidence interval is published ("ÖRNEKLEM YETERSİZ").
- Pure functions over mapping-like or attribute-like trade objects; no I/O.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MIN_SAMPLE = 30
ACTIONABLE_MIN_SCORE = 25.0
SCORE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("25-30", 25.0, 30.0),
    ("30-35", 30.0, 35.0),
    ("35-40", 35.0, 40.0),
    ("40+", 40.0, math.inf),
)


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval as percentages ``(point, low, high)``.

    Returns ``(0.0, 0.0, 0.0)`` for ``n <= 0``; clamps ``wins`` to ``[0, n]``
    and the interval to ``[0, 100]``. Values are rounded to 1 decimal.
    """
    if n <= 0:
        return 0.0, 0.0, 0.0
    wins = max(0, min(wins, n))
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    low = max(0.0, center - half) * 100
    high = min(1.0, center + half) * 100
    return round(p * 100, 1), round(low, 1), round(high, 1)


def _get(trade: Any, key: str) -> Any:
    """Read ``key`` from a mapping-like or attribute-like trade object."""
    if isinstance(trade, Mapping):
        return trade.get(key)
    return getattr(trade, key, None)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _profit_pct(trade: Any) -> float | None:
    return _as_float(_get(trade, "actual_profit_pct"))


def _score(trade: Any) -> float | None:
    return _as_float(_get(trade, "score"))


def filter_actionable(trades: Iterable[Any]) -> list[Any]:
    """Keep trades with ``score >= ACTIONABLE_MIN_SCORE`` and a known outcome."""
    out = []
    for trade in trades:
        score = _score(trade)
        if score is None or score < ACTIONABLE_MIN_SCORE:
            continue
        if _profit_pct(trade) is None:
            continue
        out.append(trade)
    return out


def _win_loss_stats(profits: Sequence[float]) -> tuple[float | None, float | None]:
    """Return ``(expectancy_r, profit_factor)`` for a profit list.

    ``expectancy_r`` needs both wins and losses. ``profit_factor`` is ``inf``
    with wins but no losses, ``0.0`` with losses but no wins, ``None`` when
    there are no trades at all.
    """
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    expectancy_r: float | None = None
    if wins and losses:
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        if avg_loss > 0:
            expectancy_r = round(avg_win / avg_loss, 2)
    profit_factor: float | None
    if losses:
        profit_factor = round(sum(wins) / abs(sum(losses)), 2)
    elif wins:
        profit_factor = math.inf
    else:
        profit_factor = None
    return expectancy_r, profit_factor


@dataclass(frozen=True)
class BandMetrics:
    """Per-score-band statistics for actionable closed trades."""

    label: str
    count: int
    wins: int
    win_rate_pct: float
    wilson_low_pct: float
    wilson_high_pct: float
    avg_profit_pct: float
    expectancy_r: float | None
    profit_factor: float | None
    sufficient: bool


def compute_band_metrics(trades: Iterable[Any], min_sample: int = MIN_SAMPLE) -> list[BandMetrics]:
    """Bucket actionable trades into ``SCORE_BANDS`` (lower <= score < upper).

    Always returns one ``BandMetrics`` per band, in ``SCORE_BANDS`` order,
    including empty bands with zeroed values.
    """
    profits_by_band: dict[str, list[float]] = {label: [] for label, _, _ in SCORE_BANDS}
    for trade in filter_actionable(trades):
        score = _score(trade)
        profit = _profit_pct(trade)
        if score is None or profit is None:
            continue
        for label, lower, upper in SCORE_BANDS:
            if lower <= score < upper:
                profits_by_band[label].append(profit)
                break
    out: list[BandMetrics] = []
    for label, _, _ in SCORE_BANDS:
        profits = profits_by_band[label]
        count = len(profits)
        wins = sum(1 for p in profits if p > 0)
        _, wilson_low, wilson_high = wilson_ci(wins, count)
        expectancy_r, profit_factor = _win_loss_stats(profits)
        out.append(
            BandMetrics(
                label=label,
                count=count,
                wins=wins,
                win_rate_pct=round(wins / count * 100, 1) if count else 0.0,
                wilson_low_pct=wilson_low,
                wilson_high_pct=wilson_high,
                avg_profit_pct=round(sum(profits) / count, 2) if count else 0.0,
                expectancy_r=expectancy_r,
                profit_factor=profit_factor,
                sufficient=count >= min_sample,
            )
        )
    return out


def _max_drawdown_pct(items: Sequence[tuple[Any, float]]) -> float:
    """Peak-to-trough drawdown of cumulative profit, ordered by close_time.

    ``items`` are ``(close_time, profit_pct)`` pairs; ``None`` close_time sorts
    last. Returns a non-negative percentage rounded to 2 decimals.
    """
    ordered = sorted(items, key=lambda item: (item[0] is None, str(item[0])))
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for _, profit in ordered:
        cumulative += profit
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return round(max_dd, 2)


def compute_portfolio_metrics(trades: Iterable[Any]) -> dict[str, Any]:
    """Aggregate metrics over actionable closed trades (exact key set).

    ``avg_loss_pct`` is signed (mean of negative profits). ``sharpe`` is the
    trade-based mean/stdev of profit percentages (``None`` if n < 2 or zero
    variance). ``max_drawdown_pct`` follows close_time ordering.
    """
    actionable = filter_actionable(trades)
    profits: list[float] = []
    close_order: list[tuple[Any, float]] = []
    for trade in actionable:
        profit = _profit_pct(trade)
        if profit is None:
            continue
        profits.append(profit)
        close_order.append((_get(trade, "close_time"), profit))
    count = len(profits)
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    win_values = [p for p in profits if p > 0]
    loss_values = [p for p in profits if p < 0]
    _, wilson_low, wilson_high = wilson_ci(wins, count)
    expectancy_r, profit_factor = _win_loss_stats(profits)
    sharpe: float | None = None
    if count >= 2:
        stdev = statistics.stdev(profits)
        if stdev > 0:
            sharpe = round((sum(profits) / count) / stdev, 2)
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / count * 100, 1) if count else 0.0,
        "wilson_low_pct": wilson_low,
        "wilson_high_pct": wilson_high,
        "avg_profit_pct": round(sum(profits) / count, 2) if count else 0.0,
        "avg_win_pct": round(sum(win_values) / len(win_values), 2) if win_values else 0.0,
        "avg_loss_pct": round(sum(loss_values) / len(loss_values), 2) if loss_values else 0.0,
        "expectancy_r": expectancy_r,
        "profit_factor": profit_factor,
        "max_drawdown_pct": _max_drawdown_pct(close_order),
        "sharpe": sharpe,
        "sufficient": count >= MIN_SAMPLE,
    }


def format_performance_section(
    trades: Iterable[Any],
    benchmark_return_pct: float | None = None,
    min_sample: int = MIN_SAMPLE,
) -> list[str]:
    """Render the daily-report performance section as markdown lines.

    Headline bullets cover actionable trades only; the score-band table shows
    Wilson intervals only for bands with ``count >= min_sample``.
    """
    actionable = filter_actionable(trades)
    lines = ["## 8. Performans Özeti (Paper Trading)", ""]
    if not actionable:
        lines.append("Kapalı actionable (skor ≥ 25) paper trade henüz yok.")
        lines.append("")
        return lines
    metrics = compute_portfolio_metrics(actionable)
    bands = compute_band_metrics(actionable, min_sample)
    count = metrics["count"]
    lines.append(f"- Actionable kapalı işlem: {count}")
    if count < min_sample:
        lines.append(
            f"- Kazanma oranı: %{metrics['win_rate_pct']:.1f} (n={count}) — "
            f"**ÖRNEKLEM YETERSİZ (n<{min_sample})**; güven aralığı yayınlanmaz."
        )
    else:
        lines.append(
            f"- Kazanma oranı: %{metrics['win_rate_pct']:.1f} "
            f"(Wilson %95 GA: %{metrics['wilson_low_pct']:.1f}"
            f"–%{metrics['wilson_high_pct']:.1f}, n={count})"
        )
    if metrics["expectancy_r"] is None:
        lines.append("- Expectancy (R): N/A (hesaplanamadı)")
    else:
        lines.append(f"- Expectancy (R): {metrics['expectancy_r']:.2f}")
    profit_factor = metrics["profit_factor"]
    if profit_factor is None:
        lines.append("- Profit Factor: N/A")
    elif math.isinf(profit_factor):
        lines.append("- Profit Factor: ∞ (kayıp işlem yok)")
    else:
        lines.append(f"- Profit Factor: {profit_factor:.2f}")
    lines.append(f"- Maks Drawdown (işlem bazlı): %{metrics['max_drawdown_pct']:.2f}")
    if metrics["sharpe"] is None:
        lines.append("- Sharpe (işlem bazlı): N/A")
    else:
        lines.append(f"- Sharpe (işlem bazlı): {metrics['sharpe']:.2f}")
    if benchmark_return_pct is not None:
        total = sum(p for t in actionable if (p := _profit_pct(t)) is not None)
        alpha = total - benchmark_return_pct
        lines.append(
            "- XU100 karşılaştırma: strateji toplam (eşit ağırlık) "
            f"%{total:.2f} vs benchmark %{benchmark_return_pct:.2f} "
            f"→ alpha %{alpha:+.2f}"
        )
    lines.append("")
    lines.append("| Skor Bandı | n | Kazanma % | Wilson %95 GA | Ort. Getiri % |")
    lines.append("|---|---|---|---|---|")
    for band in bands:
        if band.sufficient:
            gauge = f"%{band.wilson_low_pct:.1f}–%{band.wilson_high_pct:.1f}"
        else:
            gauge = "YETERSİZ"
        lines.append(
            f"| {band.label} | {band.count} | %{band.win_rate_pct:.1f} "
            f"| {gauge} | %{band.avg_profit_pct:+.2f} |"
        )
    lines.append("")
    lines.append(
        "*Headline istatistikler yalnızca actionable işlemleri (skor ≥ 25) kapsar; "
        "RADAR (20–25) işlemleri ayrı kalibrasyon deneyi olarak izlenir.*"
    )
    if count < min_sample:
        lines.append("*n < 30: güven aralığı ve lansman iddiası yayınlanmaz.*")
    lines.append("")
    return lines
