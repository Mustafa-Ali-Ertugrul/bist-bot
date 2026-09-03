"""Tests for scripts/retail_economics.py."""

from __future__ import annotations

import pandas as pd
import pytest
from scripts.retail_economics import monthly_series, simulate_portfolio


def _row(
    ticker: str,
    entry: str,
    exit_: str,
    net_pct: float,
    win: bool,
    score: float = 50.0,
    entry_ref: float = 100.0,
    stop_loss: float = 95.0,
) -> dict:
    return {
        "ticker": ticker,
        "signal_date": pd.Timestamp(entry),
        "entry_date": pd.Timestamp(entry),
        "exit_date": pd.Timestamp(exit_),
        "net_return_pct": net_pct,
        "win": win,
        "complete": True,
        "score": score,
        "entry_ref": entry_ref,
        "stop_loss": stop_loss,
    }


def test_simulate_portfolio_skips_when_book_full() -> None:
    # 6 signals enter on the same day; with max_open=5 the 6th must be skipped.
    rows = [_row(f"T{i}.IS", "2026-01-05", "2026-01-12", 1.0, True) for i in range(6)]
    df = pd.DataFrame(rows)
    taken, skipped = simulate_portfolio(df, position_tl=20_000.0, max_open=5)
    assert len(taken) == 5
    assert skipped == 1
    assert taken.pnl_tl.iloc[0] == pytest.approx(200.0)


def test_monthly_series_fills_missing_months_with_zero() -> None:
    rows = [
        _row("AAA.IS", "2026-01-05", "2026-01-12", 2.0, True),
        _row("BBB.IS", "2026-03-02", "2026-03-09", -1.0, False),
    ]
    df = pd.DataFrame(rows)
    taken, _ = simulate_portfolio(df, position_tl=20_000.0, max_open=5)
    monthly = monthly_series(taken)
    # Jan, Feb (gap), Mar must all be present; Feb = 0.
    assert len(monthly) == 3
    assert monthly.iloc[1] == 0.0
    assert monthly.iloc[0] == pytest.approx(400.0)
    assert monthly.iloc[2] == pytest.approx(-200.0)


def test_rank_by_score_prefers_high_score_when_book_full() -> None:
    # Same entry day, 6 candidates, 5 slots: fifo skips the last row,
    # score-ranking skips the lowest-score row regardless of file order.
    rows = [
        _row("LOW.IS", "2026-01-05", "2026-01-12", 1.0, True, score=10.0),
        *[
            _row(f"H{i}.IS", "2026-01-05", "2026-01-12", 1.0, True, score=50.0 + i)
            for i in range(5)
        ],
    ]
    df = pd.DataFrame(rows)

    fifo_taken, fifo_skipped = simulate_portfolio(
        df, position_tl=20_000.0, max_open=5, rank_by="fifo"
    )
    assert fifo_skipped == 1
    assert "LOW.IS" in set(fifo_taken.ticker)  # fifo keeps file order

    score_taken, score_skipped = simulate_portfolio(
        df, position_tl=20_000.0, max_open=5, rank_by="score"
    )
    assert score_skipped == 1
    assert "LOW.IS" not in set(score_taken.ticker)  # lowest score skipped


def test_risk_sizing_scales_position_by_stop_distance() -> None:
    # Tight stop (2% distance) -> position capped; wide stop (10%) -> smaller
    # position; invalid stop (0 distance) -> skipped like the live bot.
    rows = [
        _row("TIGHT.IS", "2026-01-05", "2026-01-12", 1.0, True, stop_loss=98.0),
        _row("WIDE.IS", "2026-01-05", "2026-01-12", 1.0, True, stop_loss=90.0),
        _row("NOSTOP.IS", "2026-01-05", "2026-01-12", 1.0, True, stop_loss=100.0),
    ]
    df = pd.DataFrame(rows)
    taken, _ = simulate_portfolio(
        df,
        position_tl=50_000.0,
        max_open=5,
        sizing="risk",
        risk_budget_tl=2_000.0,
        position_cap_tl=50_000.0,
    )
    assert set(taken.ticker) == {"TIGHT.IS", "WIDE.IS"}  # NOSTOP skipped
    tight = taken[taken.ticker == "TIGHT.IS"].iloc[0]
    wide = taken[taken.ticker == "WIDE.IS"].iloc[0]
    # tight: min(2000/0.02, 50000) = 50k (capped); wide: min(2000/0.10, 50000) = 20k
    assert tight.position_tl == pytest.approx(50_000.0)
    assert wide.position_tl == pytest.approx(20_000.0)
    # PnL uses the sized position: wide = 20k * 1% = 200 TL
    assert wide.pnl_tl == pytest.approx(200.0)


def test_market_scale_halves_and_blocks_positions() -> None:
    # scale=0.5 halves the position on day 1; scale=0 blocks day 2 entirely.
    scale = pd.Series(
        [0.5, 0.0],
        index=[pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")],
    )
    rows = [
        _row("HALF.IS", "2026-01-05", "2026-01-12", 2.0, True),
        _row("BLOCKED.IS", "2026-01-06", "2026-01-13", 2.0, True),
    ]
    df = pd.DataFrame(rows)
    taken, _ = simulate_portfolio(df, position_tl=20_000.0, max_open=5, market_scale=scale)
    assert set(taken.ticker) == {"HALF.IS"}  # blocked day skipped
    # 20k * 0.5 scale * 2% = 200 TL
    assert taken.pnl_tl.iloc[0] == pytest.approx(200.0)
