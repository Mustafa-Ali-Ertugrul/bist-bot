"""Faz 1: gap-entry açılış boşluğu filtresi — birim testleri."""

from __future__ import annotations

import argparse

import pandas as pd
import pytest
import scripts.recalibrate_champion as rc


def _frame(n: int = 6) -> pd.DataFrame:
    """Minimal synthetic frame: close/open/atr/score/enter_signal/calculated_stop."""
    rows = []
    for i in range(n):
        close = 100.0 + i * 0.5
        rows.append(
            {
                "close": close,
                "open": close,
                "low": close - 1.0,
                "high": close + 1.0,
                "atr": 1.5,
                "score": 30.0,
                "enter_signal": True,
                "calculated_stop": close * 0.95,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1. parity: flags off → helper never called
# ---------------------------------------------------------------------------


def test_flags_off_is_noop_parity(monkeypatch):
    calls = []

    def _stub(df: pd.DataFrame, *, gap_pct=None, gap_atr=None) -> pd.Series:
        calls.append((gap_pct, gap_atr))
        return pd.Series(False, index=df.index)

    monkeypatch.setattr(rc, "gap_entry_filter_mask", _stub)
    monkeypatch.setattr(rc, "_GAP_ENTRY_PCT", None)
    monkeypatch.setattr(rc, "_GAP_ENTRY_ATR", None)

    df = _frame().copy()
    df["score"] = 30.0
    df["enter_signal"] = True

    bt = rc.BandedBacktester(
        initial_capital=10_000,
        strategy_params=rc.StrategyParams.champion_wr(),
    )
    bt._precalculate_signals(df.copy())

    assert len(calls) == 0, "helper must not be called when both flags are None"


# ---------------------------------------------------------------------------
# 2. gap_pct mask
# ---------------------------------------------------------------------------


def test_gap_mask_pct_blocks_only_down_gaps():
    # row: 0    1     2      3    4   5
    # gap: NaN  -2.0  -1.99  -3.0 +5.0  0.0
    rows = []
    closes = [100.0, 98.0, 98.01, 97.0, 105.0, 100.0]
    opens = [100.0, 96.0, 98.01, 94.0, 105.0, 100.0]
    for c, o in zip(closes, opens, strict=True):
        rows.append(
            {
                "close": c,
                "open": o,
                "low": c - 1.0,
                "atr": 1.0,
                "score": 30.0,
                "enter_signal": True,
                "calculated_stop": c * 0.95,
            }
        )
    df = pd.DataFrame(rows)
    bad = rc.gap_entry_filter_mask(df, gap_pct=2.0, gap_atr=None)
    # row 5: prev_close=105, open=100 → gap = -4.76% → blocked
    expected = [False, True, False, True, False, True]
    assert bad.tolist() == expected, f"expected {expected}, got {bad.tolist()}"


# ---------------------------------------------------------------------------
# 3. ATR uses shifted ATR (no look-ahead)
# ---------------------------------------------------------------------------


def test_gap_mask_atr_uses_shifted_atr():
    rows = []
    # bar 0: atr=1.0, bar 1: atr=10.0 (huge ATR at current bar — must NOT be used)
    closes = [100.0, 95.0]
    opens = [100.0, 90.0]  # gap = (90-100)/100 = -10%
    atrs = [1.0, 10.0]  # atr[1]=10 but we use atr.shift(1)=1.0
    for c, o, a in zip(closes, opens, atrs, strict=True):
        rows.append(
            {
                "close": c,
                "open": o,
                "low": c - 1.0,
                "atr": a,
                "score": 30.0,
                "enter_signal": True,
                "calculated_stop": c * 0.95,
            }
        )
    df = pd.DataFrame(rows)
    # gap_atr=1.5: |gap| = 10% > 1.5*1.0=1.5 → blocked (uses atr[0]=1.0)
    # If unshifted atr[1]=10 were used: 1.5*10=15, |gap|=10 < 15 → NOT blocked
    bad = rc.gap_entry_filter_mask(df, gap_pct=None, gap_atr=1.5)
    assert bad.iloc[1], "must use atr.shift(1) — unshifted atr would not block"


# ---------------------------------------------------------------------------
# 4. ATR only down + union with pct
# ---------------------------------------------------------------------------


def test_gap_mask_atr_only_down_and_union():
    rows = []
    # bar 1: up gap (+3%) — ATR rule must NOT block
    # bar 2: down gap -1%, atr=1.0, gap_atr=2.0 → not blocked by ATR (1 < 2)
    # bar 3: down gap -3%, atr=1.0, gap_atr=2.0 → blocked by ATR
    closes = [100.0, 103.0, 102.0, 97.0]
    opens = [100.0, 106.0, 102.0, 94.0]
    atrs = [1.0, 1.0, 1.0, 1.0]
    for c, o, a in zip(closes, opens, atrs, strict=True):
        rows.append(
            {
                "close": c,
                "open": o,
                "low": c - 1.0,
                "atr": a,
                "score": 30.0,
                "enter_signal": True,
                "calculated_stop": c * 0.95,
            }
        )
    df = pd.DataFrame(rows)
    bad = rc.gap_entry_filter_mask(df, gap_pct=None, gap_atr=2.0)
    assert not bad.iloc[1], "up gap must never be blocked by ATR rule"
    assert not bad.iloc[2], "down gap smaller than ATR threshold → keep"
    assert bad.iloc[3], "down gap larger than ATR threshold → block"

    # both flags set → union
    bad_both = rc.gap_entry_filter_mask(df, gap_pct=2.0, gap_atr=2.0)
    assert (bad_both >= bad).all()

    # both None → all False
    none_bad = rc.gap_entry_filter_mask(df, gap_pct=None, gap_atr=None)
    assert not none_bad.any()


# ---------------------------------------------------------------------------
# 5. first bar NaN kept
# ---------------------------------------------------------------------------


def test_first_bar_nan_kept():
    df = _frame(n=1).copy()
    bad = rc.gap_entry_filter_mask(df, gap_pct=2.0, gap_atr=1.0)
    assert not bad.iloc[0]


# ---------------------------------------------------------------------------
# 6. integration: BandedBacktester masks entries
# ---------------------------------------------------------------------------


def test_banded_backtester_masks_entries(monkeypatch):
    # Stub super()._precalculate_signals to return a frame where every row
    # would pass the 28-33 band (score=30) and has enter_signal=True.
    def _stub_super(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["score"] = 30.0
        df["enter_signal"] = True
        df["calculated_stop"] = df["close"] * 0.95
        return df

    monkeypatch.setattr(rc.Backtester, "_precalculate_signals", _stub_super)
    monkeypatch.setattr(rc, "_GAP_ENTRY_PCT", None)
    monkeypatch.setattr(rc, "_GAP_ENTRY_ATR", None)

    rows = []
    closes = [100.0, 95.0]  # bar 1: -5% down gap
    opens = [100.0, 90.0]
    atrs = [1.0, 1.0]
    for c, o, a in zip(closes, opens, atrs, strict=True):
        rows.append(
            {
                "close": c,
                "open": o,
                "low": c - 1.0,
                "atr": a,
                "score": 30.0,
                "enter_signal": True,
                "calculated_stop": c * 0.95,
            }
        )
    df = pd.DataFrame(rows)

    bt = rc.BandedBacktester(
        initial_capital=10_000,
        strategy_params=rc.StrategyParams.champion_wr(),
    )

    # flags None → entry kept
    result_off = bt._precalculate_signals(df.copy())
    assert result_off["enter_signal"].iloc[1]

    # gap_entry_pct=2.0 → -5% gap blocked
    monkeypatch.setattr(rc, "_GAP_ENTRY_PCT", 2.0)
    result_on = bt._precalculate_signals(df.copy())
    assert not result_on["enter_signal"].iloc[1]

    # reset
    monkeypatch.setattr(rc, "_GAP_ENTRY_PCT", None)


# ---------------------------------------------------------------------------
# 7. CLI flags
# ---------------------------------------------------------------------------


def _minimal_argv(overrides: list[str] | None = None) -> list[str]:
    base = ["--mode", "diagnose", "--out", "NUL"]
    return base + (overrides or [])


def test_main_cli_flags(monkeypatch):
    captured = {}

    def _stub_diagnose(args: argparse.Namespace) -> int:
        captured["pct"] = rc._GAP_ENTRY_PCT
        captured["atr"] = rc._GAP_ENTRY_ATR
        captured["config"] = rc.stop_cap_config()
        return 0

    def _stub_search(args: argparse.Namespace) -> int:
        return 0

    monkeypatch.setattr(rc, "cmd_diagnose", _stub_diagnose)
    monkeypatch.setattr(rc, "cmd_search", _stub_search)
    monkeypatch.setattr(rc, "_GAP_ENTRY_PCT", None)
    monkeypatch.setattr(rc, "_GAP_ENTRY_ATR", None)

    # validation: --gap-entry-pct 0 → SystemExit
    with pytest.raises(SystemExit):
        rc.main(_minimal_argv(["--gap-entry-pct", "0"]))

    # valid flags
    rc.main(_minimal_argv(["--gap-entry-pct", "3", "--gap-entry-atr", "1.5"]))
    assert captured["pct"] == 3.0
    assert captured["atr"] == 1.5
    assert captured["config"]["gap_entry_pct"] == 3.0
    assert captured["config"]["gap_entry_atr"] == 1.5

    # reset
    monkeypatch.setattr(rc, "_GAP_ENTRY_PCT", None)
    monkeypatch.setattr(rc, "_GAP_ENTRY_ATR", None)
