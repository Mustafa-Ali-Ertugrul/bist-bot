"""Tests for scripts/diagnose_signal_edge.py (Deney E, phases 0-1).

Synthetic-data coverage: forward returns on both bases, censoring rules,
matched-baseline exclusions, block bootstrap behaviour, Spearman IC sign,
BH FDR, and the parity seam between the script's signal extraction and the
canonical ``Backtester._precalculate_signals`` path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diagnose_signal_edge as dse  # noqa: E402

from bist_bot.backtest.engine import Backtester  # noqa: E402
from bist_bot.backtest.models import CostModel  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402

# ---------------------------------------------------------------------------
# forward_return
# ---------------------------------------------------------------------------


def test_forward_return_basis_i_and_ii():
    closes = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0])
    opens = closes - 0.5
    # signal day t=2 (close 12), entry bar pos=3
    # basis i: close[2] -> close[2+3] = 12 -> 15 = +25%
    assert dse.forward_return(closes, opens, pos=3, horizon=3, basis="i") == pytest.approx(0.25)
    # basis ii: open[3] = 12.5 -> close[5] = 15 = +20%
    assert dse.forward_return(closes, opens, pos=3, horizon=3, basis="ii") == pytest.approx(0.20)


def test_forward_return_censoring():
    closes = np.arange(10.0, 15.0)
    opens = closes
    # pos=4, h=5 needs close at index 8 -> ok (n=5? no, len=5, idx max 4) -> None
    assert dse.forward_return(closes, opens, pos=4, horizon=5, basis="i") is None
    assert dse.forward_return(closes, opens, pos=0, horizon=1, basis="i") is None
    assert dse.forward_return(closes, opens, pos=4, horizon=1, basis="i") is not None


# ---------------------------------------------------------------------------
# extract_signal_rows parity with the canonical engine path
# ---------------------------------------------------------------------------


def _trending_frame(n: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rows = []
    for i, d in enumerate(dates):
        close = 100.0 + i * 0.5
        rows.append(
            {
                "date": d,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close + 0.1,
                "volume": 10_000.0,
                "volume_sma_20": 10_000.0,
                "atr": 1.5,
                "rsi": 28.0,
                "sma_cross": "GOLDEN_CROSS",
                "macd_cross": "BULLISH",
                "bb_position": "BELOW_LOWER",
                "sma_5": close + 0.5,
                "sma_20": close - 0.5,
                "ema_200": close - 5.0,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def test_extract_signal_rows_matches_engine_precalculated():
    bt = Backtester(strategy_params=StrategyParams.conservative(), target_rr=2.0)
    frame = _trending_frame()
    sig = dse.precalculated_signals(frame, bt)
    rows = dse.extract_signal_rows(sig, "T.IS")
    expected = np.flatnonzero(sig["enter_signal"].to_numpy(dtype=bool))
    assert [r["pos"] for r in rows] == [int(i) for i in expected if i >= 1]
    for r in rows:
        i = int(r["pos"])
        assert pd.Timestamp(r["entry_date"]) == sig.index[i]
        assert pd.Timestamp(r["signal_date"]) == sig.index[i - 1]


def test_extract_signal_rows_complete_rule():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    sig = pd.DataFrame(
        {
            "enter_signal": [False] * 5 + [True] + [False] * 4,
            "score": [30.0] * 10,
        },
        index=idx,
    )
    rows = dse.extract_signal_rows(sig, "T.IS")
    # entry at pos=5, n=10: 5 + 4 = 9 <= 9 -> complete
    assert rows[0]["complete"] is True
    sig2 = sig.copy()
    sig2["enter_signal"] = [False] * 6 + [True] + [False] * 3
    rows2 = dse.extract_signal_rows(sig2, "T.IS")
    # entry at pos=6: 6 + 4 = 10 > 9 -> censored
    assert rows2[0]["complete"] is False


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_block_bootstrap_ci_covers_true_mean_on_iid_data():
    rng = np.random.default_rng(0)
    diffs = rng.normal(0.01, 0.05, size=400)
    dates = pd.date_range("2024-01-01", periods=400, freq="D").to_numpy()
    mean_, lo, hi = dse.block_bootstrap_ci(diffs, dates, block=10, n_boot=500, seed=42)
    assert lo < 0.01 < hi
    assert mean_ == pytest.approx(float(diffs.mean()))


def test_block_bootstrap_handles_short_series():
    diffs = np.array([0.01, -0.02, 0.03])
    dates = pd.date_range("2024-01-01", periods=3, freq="D").to_numpy()
    mean_, lo, hi = dse.block_bootstrap_ci(diffs, dates, block=10, n_boot=50, seed=1)
    assert np.isfinite(mean_)


def test_spearman_ic_sign_and_noise():
    x = np.arange(100, dtype=float)
    y_up = x + np.random.default_rng(2).normal(0, 5, 100)
    rho, p = dse.spearman_ic(x, y_up)
    assert rho > 0.8 and p < 0.001
    y_noise = np.random.default_rng(3).normal(0, 1, 100)
    rho2, _ = dse.spearman_ic(x, y_noise)
    assert abs(rho2) < 0.3
    # constant feature -> undefined
    rho3, p3 = dse.spearman_ic(np.ones(10), np.arange(10, dtype=float))
    assert np.isnan(rho3) and np.isnan(p3)


def test_bh_fdr_controls_family():
    pvals = [0.001, 0.002, 0.5, 0.9, float("nan")]
    keep = dse.bh_fdr(pvals, q=0.05)
    assert keep == [True, True, False, False, False]


def test_design_effect_increases_with_clustering():
    dates = np.repeat(pd.date_range("2024-01-01", periods=50, freq="D").to_numpy(), 5)
    rng = np.random.default_rng(4)
    # strongly clustered values: same value within a date
    per_date = rng.normal(0, 1, 50)
    values = np.repeat(per_date, 5)
    deff, m = dse.design_effect(dates, values)
    assert m == pytest.approx(5.0)
    assert deff > 1.5


def test_n_required_wr60_scales_with_design_effect():
    assert dse.n_required_wr60(1.0) < dse.n_required_wr60(4.0)


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------


def test_net_of_cost_reduces_return():
    cost = CostModel()
    assert dse.net_of_cost(0.01, cost) < 0.01
    assert dse.net_of_cost(0.0, cost) < 0.0  # fees alone lose money
    # sanity: ~0.4-0.5% round-trip drag at gross 0
    assert dse.net_of_cost(0.0, cost) == pytest.approx(-0.0049, abs=0.001)


# ---------------------------------------------------------------------------
# compute_row_features parity with production scorers
# ---------------------------------------------------------------------------


def test_compute_row_features_matches_production_scorers():
    from bist_bot.strategy.scoring import (
        score_momentum,
        score_structure,
        score_trend,
        score_volume,
    )

    params = StrategyParams.conservative()
    frame = _trending_frame()
    j = 60
    hist = frame.iloc[: j + 1]
    last, prev = frame.iloc[j], frame.iloc[j - 1]
    feats = dse.compute_row_features(params, frame, j)
    assert feats["score_momentum"] == pytest.approx(score_momentum(params, last, prev)[0])
    assert feats["score_trend"] == pytest.approx(score_trend(params, last, prev, hist)[0])
    assert feats["score_volume"] == pytest.approx(score_volume(params, last, prev)[0])
    assert feats["score_structure"] == pytest.approx(score_structure(params, last)[0])
    assert feats["score_total"] == pytest.approx(
        feats["score_momentum"]
        + feats["score_trend"]
        + feats["score_volume"]
        + feats["score_structure"]
    )


# ---------------------------------------------------------------------------
# Parity anchor
# ---------------------------------------------------------------------------


def test_assert_parity_passes_on_matching_set(tmp_path):
    signals = pd.DataFrame(
        [
            {
                "ticker": "A.IS",
                "signal_date": pd.Timestamp("2024-01-02"),
                "entry_date": pd.Timestamp("2024-01-03"),
                "pos": 5,
                "score": 30.0,
                "complete": True,
            }
        ]
    )
    ref = tmp_path / "ref.csv"
    ref.write_text("ticker,signal_date,entry_date\nA.IS,2024-01-02,2024-01-03\n", encoding="utf-8")
    dse.assert_parity(signals, ref)


def test_assert_parity_raises_on_mismatch(tmp_path):
    signals = pd.DataFrame(
        [
            {
                "ticker": "A.IS",
                "signal_date": pd.Timestamp("2024-01-02"),
                "entry_date": pd.Timestamp("2024-01-03"),
                "pos": 5,
                "score": 30.0,
                "complete": True,
            }
        ]
    )
    ref = tmp_path / "ref.csv"
    ref.write_text("ticker,signal_date,entry_date\nA.IS,2024-01-05,2024-01-06\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="parity FAILED"):
        dse.assert_parity(signals, ref)


# ---------------------------------------------------------------------------
# simulate_exit
# ---------------------------------------------------------------------------


def _bars(closes, spread=0.02):
    closes = np.asarray(closes, dtype=float)
    opens = closes.copy()
    highs = closes * (1 + spread)
    lows = closes * (1 - spread)
    exits = np.zeros(len(closes), dtype=bool)
    atr = np.full(len(closes), 1.0)
    return opens, highs, lows, closes, exits, atr


def test_simulate_exit_same_bar_stop_wins_on_tie():
    # bar 1: low dips below stop AND high above target -> stop-first rule.
    opens = np.array([100.0, 100.5, 100.0])
    highs = np.array([100.5, 107.0, 100.5])
    lows = np.array([99.0, 96.0, 99.5])
    closes = np.array([100.0, 100.5, 100.0])
    exits = np.zeros(3, dtype=bool)
    atr = np.full(3, 1.0)
    reason, idx, ref, _mfe = dse.simulate_exit(
        opens, highs, lows, closes, exits, atr, 0, stop=97.0, rr=2.0, max_hold=3
    )
    assert reason == "STOP_LOSS" and idx == 1 and ref == 97.0


def test_simulate_exit_take_profit():
    # bar 1: open below target, high crosses it intraday -> TAKE_PROFIT.
    opens = np.array([100.0, 101.0, 102.0])
    highs = np.array([100.5, 104.0, 102.5])
    lows = np.array([99.0, 100.5, 101.5])
    closes = np.array([100.0, 103.0, 102.0])
    exits = np.zeros(3, dtype=bool)
    atr = np.full(3, 1.0)
    reason, idx, ref, _mfe = dse.simulate_exit(
        opens, highs, lows, closes, exits, atr, 0, stop=97.0, rr=1.0, max_hold=3
    )
    assert reason == "TAKE_PROFIT" and idx == 1 and ref == pytest.approx(103.0)


def test_simulate_exit_max_hold_forces_close():
    opens, highs, lows, closes, exits, atr = _bars([100.0, 101.0, 102.0, 103.0, 104.0])
    reason, idx, ref, _mfe = dse.simulate_exit(
        opens, highs, lows, closes, exits, atr, 0, stop=90.0, rr=5.0, max_hold=3
    )
    assert reason == "MAX_HOLD" and idx == 2 and ref == 102.0


def test_simulate_exit_signal_open_beats_hold():
    opens, highs, lows, closes, exits, atr = _bars([100.0, 101.0, 102.0, 103.0])
    exits[2] = True
    reason, idx, ref, _mfe = dse.simulate_exit(
        opens, highs, lows, closes, exits, atr, 0, stop=90.0, rr=5.0, max_hold=4
    )
    assert reason == "SIGNAL_OPEN" and idx == 2 and ref == 102.0


def test_simulate_exit_trailing_stop_ratchets():
    # Price rises then falls: trailing k*ATR from peak catches the reversal.
    closes = [100.0, 106.0, 106.0, 99.0, 98.0]
    opens, highs, lows, closes, exits, atr = _bars(closes)
    reason, idx, ref, _mfe = dse.simulate_exit(
        opens,
        highs,
        lows,
        closes,
        exits,
        atr,
        0,
        stop=95.0,
        rr=5.0,
        max_hold=5,
        trailing_k=1.5,
    )
    assert reason in {"STOP_LOSS", "STOP_GAP"}
    assert ref >= 95.0  # trailing stop never below the initial stop
