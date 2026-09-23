"""Unit tests for the shared causal alpha-trend simulator.

Regression guards for the Round-2 intrabar look-ahead fix:
- a bar that makes a new close-peak must NOT be exited using the trail
  derived from its own close (the old biased code did);
- gap-through-stop exits at the open;
- the entry bar's low IS tested against the initial stop (day-0 stop-out);
- the minimum stop cushion floor (entry*0.985);
- entries execute at the NEXT bar's open after a signal close.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_bot.backtest.alpha_trend_sim import StockData, simulate_strategy

TRAIL = 3.0
STOP_PCT = 4.5
COST = 0.0
N = 80


def make_sd(
    closes: list[float],
    sig_at: list[int],
    atr: float = 2.0,
    lows: list[float] | None = None,
) -> StockData:
    assert len(closes) == N
    dates = pd.date_range("2024-01-01", periods=N, freq="D")
    c = np.array(closes, dtype=float)
    o = c.copy()
    h = c + 1.0
    lo = np.array(lows, dtype=float) if lows is not None else c - 1.0
    a = np.full(N, atr)
    sig = np.zeros(N, dtype=bool)
    for i in sig_at:
        sig[i] = True
    bull = np.ones(N, dtype=bool)
    return StockData("TEST.IS", dates, o, h, lo, c, a, sig, bull)


def base_closes(**overrides: float) -> list[float]:
    closes = [100.0] * N
    for idx, val in overrides.items():
        closes[int(idx)] = val
    return closes


def test_same_bar_new_peak_reversal_waits_for_next_bar():
    """Bar 63 yeni zirve kapanışı (110) yapar; low 102 YENİ trail'i (104)
    deler ama lag'li trail'i (97) delmez -> bar 63'te çıkış YOK.
    Bar 64 low 100, bar 63 kapanışından türelenen trail'e (104) vurur."""
    closes = base_closes(**{"63": 110.0, "64": 106.0})
    lows = [c - 1.0 for c in closes]
    lows[63] = 102.0
    lows[64] = 100.0
    sd = make_sd(closes, sig_at=[61], lows=lows)

    trades = simulate_strategy(sd, TRAIL, STOP_PCT, COST)

    assert len(trades) == 1
    trade = trades[0]
    # Giriş: sinyal bar 61 -> sonraki bar (62) açılışı.
    assert trade.entry_date == sd.dates[62]
    assert trade.entry_price == 100.0
    # Çıkış bar 63'te DEĞİL, bar 64'te (eski bias'lı kod 63'te 104'ten çıkarıyordu).
    assert trade.exit_date == sd.dates[64]
    assert trade.exit_price == 104.0
    assert trade.exit_reason == "TRAILING_STOP"
    assert trade.holding_bars == 2


def test_gap_through_trail_exits_at_open():
    """Açılış lag'li trail'in altındaysa dolgu açılıştan olur."""
    closes = base_closes(**{"63": 110.0, "64": 95.0})
    lows = [c - 1.0 for c in closes]
    lows[63] = 102.0
    lows[64] = 90.0
    sd = make_sd(closes, sig_at=[61], lows=lows)

    trades = simulate_strategy(sd, TRAIL, STOP_PCT, COST)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_date == sd.dates[64]
    assert trade.exit_price == 95.0  # min(open=95, trail=104)
    assert trade.exit_reason == "TRAILING_STOP"


def test_day0_stop_out_on_entry_bar():
    """Giriş barının low'u ilk stop'u delerse aynı barda çıkılır (gün-0 stop)."""
    closes = base_closes()
    lows = [c - 1.0 for c in closes]
    lows[62] = 96.0  # stop = max(100-3, 95.5) = 97 -> 96 <= 97
    sd = make_sd(closes, sig_at=[61], lows=lows)

    trades = simulate_strategy(sd, TRAIL, STOP_PCT, COST)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_date == sd.dates[62]
    assert trade.exit_price == 97.0
    assert trade.exit_reason == "INITIAL_STOP"
    assert trade.holding_bars == 0
    assert trade.net_pnl_pct == -3.0


def test_min_stop_cushion_floor_is_985():
    """ATR küçükse stop cushion < %1.5 olur -> taban entry*0.985 uygulanır.

    ATR=0.5: raw stop = 99.25 (cushion %0.75) -> floor 98.5.
    Bar 63 low 98 <= 98.5 -> INITIAL_STOP @ 98.5.
    """
    closes = base_closes()
    lows = [c - 1.0 for c in closes]
    lows[63] = 98.0
    sd = make_sd(closes, sig_at=[61], atr=0.5, lows=lows)

    trades = simulate_strategy(sd, TRAIL, STOP_PCT, COST)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_price == 98.5
    assert trade.exit_reason == "INITIAL_STOP"


def test_entry_executes_at_next_bar_open():
    """Sinyal bar 61 kapanışı 107; giriş bar 62 açılışı (100) olmalı."""
    closes = base_closes(**{"61": 107.0})
    sd = make_sd(closes, sig_at=[61])

    trades = simulate_strategy(sd, TRAIL, STOP_PCT, COST)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_date == sd.dates[62]
    assert trade.entry_price == 100.0
    assert trade.exit_reason == "FINAL_CLOSE"
