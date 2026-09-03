"""Tests for the paper-trade performance metrics engine."""

from __future__ import annotations

import math
from collections import namedtuple

import pytest

from bist_bot.reports.performance import (
    ACTIONABLE_MIN_SCORE,
    MIN_SAMPLE,
    BandMetrics,
    compute_band_metrics,
    compute_portfolio_metrics,
    filter_actionable,
    format_performance_section,
    wilson_ci,
)


def _actionable_trades(n: int, wins: int) -> list[dict]:
    trades = []
    for i in range(n):
        profit = 2.0 if i < wins else -1.0
        trades.append(
            {
                "score": 26.0 + (i % 4) * 5,
                "actual_profit_pct": profit,
                "close_time": f"2026-08-{(i % 20) + 1:02d}T18:00:00+00:00",
            }
        )
    return trades


def test_wilson_ci_zero_n():
    assert wilson_ci(0, 0) == (0.0, 0.0, 0.0)


def test_wilson_ci_known_values():
    point, low, high = wilson_ci(60, 100)
    assert point == 60.0
    assert low == pytest.approx(50.2, abs=0.5)
    assert high == pytest.approx(69.1, abs=0.5)


def test_wilson_ci_extremes():
    assert wilson_ci(0, 50)[1] == 0.0
    assert wilson_ci(50, 50)[2] == 100.0


def test_filter_actionable_excludes_invalid():
    trades = [
        {"ticker": "A", "score": None, "actual_profit_pct": 1.0},
        {"ticker": "B", "score": 30.0, "actual_profit_pct": None},
        {"ticker": "C", "score": 22.0, "actual_profit_pct": 1.0},  # RADAR band
        {"ticker": "D", "score": 25.0, "actual_profit_pct": 1.0},
        {"ticker": "E", "score": 40.0, "actual_profit_pct": -1.0},
    ]
    kept = filter_actionable(trades)
    assert [t["ticker"] for t in kept] == ["D", "E"]
    assert ACTIONABLE_MIN_SCORE == 25.0


def test_compute_band_metrics_buckets():
    trades = [
        {"score": 27.0, "actual_profit_pct": 2.0},
        {"score": 32.0, "actual_profit_pct": -1.0},
        {"score": 37.0, "actual_profit_pct": 3.0},
        {"score": 42.0, "actual_profit_pct": 1.0},
        {"score": 24.0, "actual_profit_pct": 5.0},  # below actionable threshold
        {"score": 33.0, "actual_profit_pct": None},  # no outcome yet
    ]
    bands = compute_band_metrics(trades)
    assert [b.label for b in bands] == ["25-30", "30-35", "35-40", "40+"]
    assert all(isinstance(b, BandMetrics) for b in bands)
    assert all(b.count == 1 for b in bands)
    assert all(b.sufficient is False for b in bands)
    b25, b30, b35, _b40 = bands
    assert b25.wins == 1
    assert b30.wins == 0
    assert b25.expectancy_r is None  # no losses in band
    assert b30.expectancy_r is None  # no wins in band
    assert b25.profit_factor == math.inf
    assert b30.profit_factor == 0.0
    assert b35.profit_factor == math.inf


def test_compute_portfolio_metrics_known_set():
    trades = [
        {"score": 30.0, "actual_profit_pct": 5.0, "close_time": "2026-08-17T18:00:00+00:00"},
        {"score": 30.0, "actual_profit_pct": 3.0, "close_time": "2026-08-18T18:00:00+00:00"},
        {"score": 30.0, "actual_profit_pct": -2.0, "close_time": "2026-08-19T18:00:00+00:00"},
        {"score": 30.0, "actual_profit_pct": -1.0, "close_time": "2026-08-20T18:00:00+00:00"},
    ]
    m = compute_portfolio_metrics(trades)
    assert m["count"] == 4
    assert m["wins"] == 2
    assert m["losses"] == 2
    assert m["win_rate_pct"] == 50.0
    assert m["avg_profit_pct"] == 1.25
    assert m["avg_win_pct"] == 4.0
    assert m["avg_loss_pct"] == -1.5
    assert m["expectancy_r"] == round(4.0 / 1.5, 2)
    assert m["profit_factor"] == round(8.0 / 3.0, 2)
    assert m["sharpe"] is not None
    assert m["sufficient"] is False


def test_max_drawdown_respects_close_time_order():
    def build(profits: list[float]) -> list[dict]:
        return [
            {
                "score": 30.0,
                "actual_profit_pct": p,
                "close_time": f"2026-08-{i + 1:02d}T18:00:00+00:00",
            }
            for i, p in enumerate(profits)
        ]

    # Chronological -2, +5, -4 -> cumulative -2, 3, -1; peak 3; dd 4.
    order_a = build([-2.0, 5.0, -4.0])
    # Chronological +5, -2, -4 -> cumulative 5, 3, -1; peak 5; dd 6.
    order_b = build([5.0, -2.0, -4.0])
    assert compute_portfolio_metrics(order_a)["max_drawdown_pct"] == 4.0
    assert compute_portfolio_metrics(order_b)["max_drawdown_pct"] == 6.0


def test_sharpe_none_when_single_trade():
    trades = [{"score": 30.0, "actual_profit_pct": 2.0, "close_time": "2026-08-20T18:00:00+00:00"}]
    assert compute_portfolio_metrics(trades)["sharpe"] is None


def test_format_no_trades():
    lines = format_performance_section([])
    assert lines[0] == "## 8. Performans Özeti (Paper Trading)"
    assert "henüz yok" in "\n".join(lines)


def test_format_insufficient_sample():
    text = "\n".join(format_performance_section(_actionable_trades(5, 3)))
    assert "ÖRNEKLEM YETERSİZ" in text
    assert "Wilson %95 GA:" not in text
    assert "| YETERSİZ |" in text


def test_format_sufficient_sample():
    text = "\n".join(format_performance_section(_actionable_trades(MIN_SAMPLE, 18)))
    assert "Wilson %95 GA:" in text
    assert "ÖRNEKLEM YETERSİZ" not in text


def test_format_benchmark_line():
    trades = _actionable_trades(5, 3)
    assert "XU100 karşılaştırma" not in "\n".join(format_performance_section(trades))
    text = "\n".join(format_performance_section(trades, benchmark_return_pct=1.5))
    assert "XU100 karşılaştırma" in text
    assert "alpha" in text


def test_accepts_attribute_objects():
    Trade = namedtuple("Trade", ["score", "actual_profit_pct", "close_time", "close_reason"])
    trades = [
        Trade(
            score=30.0,
            actual_profit_pct=2.0,
            close_time="2026-08-19T18:00:00+00:00",
            close_reason="TARGET",
        ),
        Trade(
            score=28.0,
            actual_profit_pct=-1.0,
            close_time="2026-08-20T18:00:00+00:00",
            close_reason="STOP",
        ),
    ]
    assert len(filter_actionable(trades)) == 2
    assert compute_portfolio_metrics(trades)["count"] == 2
