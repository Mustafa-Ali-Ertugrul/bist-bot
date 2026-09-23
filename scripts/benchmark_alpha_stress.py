"""Institutional Stress-Testing Benchmark Suite for BIST Alpha Trend Strategy.

Round-2 rebuild: every claim in this suite is MEASURED from executed
trades — no hard-coded results. The trade simulation is delegated to the
shared CAUSAL simulator (``bist_bot.backtest.alpha_trend_sim``).

  TEST 1  Bear-Market Gate Audit   : executed trade entries vs benchmark regime
                                     (signal-bar AND entry-bar, measured)
  TEST 2  Friction Curve           : 0.10%..1.50% roundtrip + REALISTIC_COSTS marker
  TEST 3  Parameter Surface        : robustness grid on the causal engine
  TEST 4  Monte Carlo (real pool)  : ACTUAL trade pool, iid + block bootstrap
                                     (entry-month clusters), 20% weight AND
                                     full position sizing
  TEST 5  Split-Half Consistency   : first vs second half by entry date

Known caveats (documented, not hidden):
  - Survivorship bias: current BIST30 members over a 2y lookback
    (point-in-time universe is a deferred follow-up phase).
  - Single 2y window (~500 bars).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_bot.backtest.alpha_trend_sim import preload_all, run_trades, trade_stats
from bist_bot.backtest.realistic_costs import REALISTIC_COSTS

BIST30_TICKERS = [
    "AKBNK.IS",
    "ALARK.IS",
    "ASELS.IS",
    "ASTOR.IS",
    "BIMAS.IS",
    "BRSAN.IS",
    "DOAS.IS",
    "EKGYO.IS",
    "ENKAI.IS",
    "EREGL.IS",
    "FROTO.IS",
    "GARAN.IS",
    "GUBRF.IS",
    "HEKTS.IS",
    "ISCTR.IS",
    "KCHOL.IS",
    "KONTR.IS",
    "KRDMD.IS",
    "ODAS.IS",
    "OYAKC.IS",
    "PETKM.IS",
    "PGSUS.IS",
    "SAHOL.IS",
    "SASA.IS",
    "SISE.IS",
    "TCELL.IS",
    "THYAO.IS",
    "TOASO.IS",
    "TUPRS.IS",
    "YKBNK.IS",
]

TRAIL = 3.0
STOP_PCT = 4.5
COST = 0.35
N_SIMS = 1000
SEED = 42
POS_WEIGHT = 0.20

FRICTION_SWEEP = [0.10, 0.20, 0.35, 0.50, 0.75, 1.00, 1.50]


def realistic_roundtrip_pct() -> float:
    """Roundtrip friction implied by REALISTIC_COSTS (bps), in percent."""
    entry_bps = (
        REALISTIC_COSTS["commission_bps"]
        + REALISTIC_COSTS["exchange_fee_bps"]
        + REALISTIC_COSTS["spread_bps"]
        + REALISTIC_COSTS["entry_slippage_bps"]
    )
    exit_bps = (
        REALISTIC_COSTS["commission_bps"]
        + REALISTIC_COSTS["exchange_fee_bps"]
        + REALISTIC_COSTS["stamp_tax_bps"]
        + REALISTIC_COSTS["bsmv_bps"]
        + REALISTIC_COSTS["spread_bps"]
        + REALISTIC_COSTS["exit_slippage_bps"]
    )
    return round((entry_bps + exit_bps) / 100.0, 3)


def benchmark_bear_gate(xu100: pd.DataFrame, trades: list) -> dict[str, object]:
    """MEASURED gate audit: executed trade entries vs benchmark regime.

    The gate applies on the SIGNAL bar (bar before entry). This audit
    verifies, from executed trades: (a) how many signal bars were bear
    (must be 0 by construction — now verified numerically, not asserted),
    and (b) how many ENTRY bars were bear (regime can flip overnight —
    the gate does not protect against this and the number is reported).
    """
    regime = xu100["market_bullish"]
    index = xu100.index
    signal_bear = 0
    entry_bear = 0
    checked = 0
    for tr in trades:
        if tr.entry_date not in index:
            continue
        checked += 1
        pos = int(index.get_loc(tr.entry_date))
        if not bool(regime.iloc[pos]):
            entry_bear += 1
        if pos > 0 and not bool(regime.iloc[pos - 1]):
            signal_bear += 1
    return {
        "trades_checked": checked,
        "signal_bar_bear_entries": signal_bear,
        "entry_bar_bear_entries": entry_bear,
        "bear_bars_in_window": int((~regime).sum()),
        "total_bars": len(regime),
    }


def benchmark_friction(xu100: pd.DataFrame, cache: dict) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    realistic = realistic_roundtrip_pct()
    for c in [*FRICTION_SWEEP, realistic]:
        st = trade_stats(run_trades(xu100, cache, TRAIL, STOP_PCT, c))
        rows.append(
            {
                "friction_pct": round(c, 3),
                "is_realistic_scenario": abs(c - realistic) < 1e-9,
                "trades": st["n"],
                "win_rate": st["win_rate"],
                "profit_factor": st["profit_factor"],
                "avg_net_pp": st["avg_net_pp"],
                "viable": st["profit_factor"] > 1.10 and st["avg_net_pp"] > 0,
            }
        )
    return rows


def benchmark_parameter_surface(xu100: pd.DataFrame, cache: dict) -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for trail in [2.0, 2.5, 3.0, 3.5]:
        for stop in [3.5, 4.5, 5.5]:
            st = trade_stats(run_trades(xu100, cache, trail, stop, COST))
            grid.append(
                {
                    "trail": trail,
                    "stop": stop,
                    "n": st["n"],
                    "wr": st["win_rate"],
                    "pf": st["profit_factor"],
                    "avg_net": st["avg_net_pp"],
                }
            )
    return grid


def _simulate_equity(seq: np.ndarray, weight: float) -> tuple[float, float]:
    """Compound a trade sequence at fixed position weight. Returns (total_ret%, max_dd%)."""
    eq = 1.0
    peak_eq = 1.0
    mdd = 0.0
    for p in seq:
        eq *= 1.0 + (p / 100.0) * weight
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq * 100.0
        if dd > mdd:
            mdd = dd
    return (eq - 1.0) * 100.0, mdd


def _sample_block_seq(block_list: list[np.ndarray], n_target: int, rng) -> np.ndarray:
    """Block bootstrap: sample whole entry-month clusters until n_target trades."""
    parts: list[np.ndarray] = []
    total = 0
    while total < n_target:
        b = block_list[int(rng.integers(0, len(block_list)))]
        parts.append(b)
        total += len(b)
    return np.concatenate(parts)[:n_target]


def benchmark_monte_carlo(trades: list) -> dict[str, object]:
    """Monte Carlo on the REAL trade pool (no re-synthesized strategies).

    Two resampling schemes:
      - iid  : trades drawn independently (ignores clustering — optimistic)
      - block: whole entry-month clusters drawn together (preserves the
               correlation of same-day / same-regime breakouts)
    Two sizing schemes: 20% position weight and FULL position.
    """
    pnls = np.array([t.net_pnl_pct for t in trades], dtype=float)
    months = pd.PeriodIndex([t.entry_date for t in trades], freq="M")
    blocks: dict[object, list[float]] = {}
    for m, p in zip(months, pnls, strict=False):
        blocks.setdefault(m, []).append(float(p))
    block_list = [np.array(v, dtype=float) for v in blocks.values()]

    rng = np.random.default_rng(SEED)
    out: dict[str, object] = {"n_simulations": N_SIMS, "pool_trades": len(pnls)}
    for scheme in ("iid", "block"):
        for weight_label, weight in (("pos20", POS_WEIGHT), ("full", 1.0)):
            mdds: list[float] = []
            finals: list[float] = []
            ruin20 = 0
            ruin35 = 0
            for _ in range(N_SIMS):
                if scheme == "iid":
                    seq = rng.choice(pnls, size=len(pnls), replace=True)
                else:
                    seq = _sample_block_seq(block_list, len(pnls), rng)
                total_ret, mdd = _simulate_equity(seq, weight)
                finals.append(total_ret)
                mdds.append(mdd)
                if mdd >= 20.0:
                    ruin20 += 1
                if mdd >= 35.0:
                    ruin35 += 1
            mdds_arr = np.array(mdds)
            finals_arr = np.array(finals)
            out[f"{scheme}_{weight_label}"] = {
                "median_return_pct": round(float(np.median(finals_arr)), 1),
                "p5_return_pct": round(float(np.percentile(finals_arr, 5)), 1),
                "median_max_dd_pct": round(float(np.median(mdds_arr)), 1),
                "p95_max_dd_pct": round(float(np.percentile(mdds_arr, 95)), 1),
                "p99_max_dd_pct": round(float(np.percentile(mdds_arr, 99)), 1),
                "prob_dd_gt_20pct": round(ruin20 / N_SIMS * 100.0, 1),
                "prob_dd_gt_35pct": round(ruin35 / N_SIMS * 100.0, 1),
            }
    return out


def benchmark_split_half(trades: list) -> dict[str, object]:
    """Split-half consistency: first vs second half of trades by entry date."""
    dates_sorted = sorted(t.entry_date for t in trades)
    median_date = dates_sorted[len(dates_sorted) // 2]
    h1 = [t for t in trades if t.entry_date < median_date]
    h2 = [t for t in trades if t.entry_date >= median_date]
    return {
        "median_date": median_date,
        "first": trade_stats(h1),
        "second": trade_stats(h2),
    }


def main():
    print("=" * 80)
    print("STRESS BENCHMARK SUITE (Round-2 rebuild: causal engine, measured claims)")
    print("=" * 80)

    print("\nLoading 2y BIST30 data (network fetch)...")
    xu100, cache = preload_all(BIST30_TICKERS, period="2y")
    print(f"Loaded {len(cache)}/30 tickers + XU100 benchmark.")
    print(
        f"Window: {xu100.index.min().date()} -> {xu100.index.max().date()} | "
        f"bull bars: {int(xu100['market_bullish'].sum())}/{len(xu100)}"
    )

    trades = run_trades(xu100, cache, TRAIL, STOP_PCT, COST)
    base = trade_stats(trades)
    print(
        f"\nBase (causal, trail={TRAIL}, stop={STOP_PCT}%, cost={COST}%): "
        f"n={base['n']}  WR={base['win_rate']}%  PF={base['profit_factor']}  "
        f"avg={base['avg_net_pp']:+.3f}pp"
    )

    print("\n" + "=" * 80)
    print("STRESS TEST 1: BEAR-MARKET GATE AUDIT (measured from executed trades)")
    print("=" * 80)
    b1 = benchmark_bear_gate(xu100, trades)
    print(f"  trades checked                : {b1['trades_checked']}")
    print(f"  bear bars in window           : {b1['bear_bars_in_window']}/{b1['total_bars']}")
    print(
        f"  entries with BEAR signal bar  : {b1['signal_bar_bear_entries']} (gate: verified numerically)"
    )
    print(
        f"  entries on BEAR entry bar     : {b1['entry_bar_bear_entries']} (overnight regime flips)"
    )
    print("  note: gate applies on the signal bar; entry-bar regime is audited above")

    print("\n" + "=" * 80)
    print("STRESS TEST 2: FRICTION & SLIPPAGE STRESS CURVE (causal engine)")
    print("=" * 80)
    b2 = benchmark_friction(xu100, cache)
    print(
        f"  {'Friction (Roundtrip)':<22} {'Trades':<8} {'Win Rate':<10} {'PF':<8} {'Avg Net':<10} {'Status'}"
    )
    print("  " + "-" * 78)
    for row in b2:
        tag = " [REALISTIC_COSTS]" if row["is_realistic_scenario"] else ""
        st = "PASS (Profitable)" if row["viable"] else "FAIL (Breakeven/Negative)"
        print(
            f"  %{row['friction_pct']:<20.3f} {row['trades']:<8} %{row['win_rate']:<9.1f} "
            f"{row['profit_factor']:<8.3f} {row['avg_net_pp']:<+9.3f}pp {st}{tag}"
        )

    print("\n" + "=" * 80)
    print("STRESS TEST 3: PARAMETER SURFACE (causal engine)")
    print("=" * 80)
    b3 = benchmark_parameter_surface(xu100, cache)
    print(
        f"  {'Trail ATR':<12} {'Max Stop':<10} {'Trades':<8} {'Win Rate':<10} {'PF':<8} {'Avg Net'}"
    )
    print("  " + "-" * 60)
    pfs = [r["pf"] for r in b3]
    for r in b3:
        print(
            f"  {r['trail']:<12.1f} %{r['stop']:<9.1f} {r['n']:<8} %{r['wr']:<9.1f} "
            f"{r['pf']:<8.3f} {r['avg_net']:<+9.3f}pp"
        )
    print(
        f"  --> Grid spread: Min PF={min(pfs):.3f} | Max PF={max(pfs):.3f} | "
        f"Mean PF={float(np.mean(pfs)):.3f} (12 combos on the same sample: "
        f"multiple-comparison caveat applies)"
    )

    print("\n" + "=" * 80)
    print(f"STRESS TEST 4: MONTE CARLO ON REAL TRADE POOL ({N_SIMS} sims)")
    print("=" * 80)
    b4 = benchmark_monte_carlo(trades)
    print(f"  pool: {b4['pool_trades']} actual trades (no re-synthesized strategies)")
    for key in ("iid_pos20", "block_pos20", "iid_full", "block_full"):
        d = b4[key]
        print(
            f"\n  [{key}]  median ret {d['median_return_pct']:+.1f}% (p5 {d['p5_return_pct']:+.1f}%) | "
            f"median maxDD {d['median_max_dd_pct']:.1f}% | "
            f"p95 maxDD {d['p95_max_dd_pct']:.1f}% | p99 maxDD {d['p99_max_dd_pct']:.1f}%"
        )
        print(
            f"      P(maxDD > 20%) = {d['prob_dd_gt_20pct']:.1f}%   "
            f"P(maxDD > 35%) = {d['prob_dd_gt_35pct']:.1f}%"
        )

    print("\n" + "=" * 80)
    print("STRESS TEST 5: SPLIT-HALF CONSISTENCY (by entry date)")
    print("=" * 80)
    b5 = benchmark_split_half(trades)
    f, s = b5["first"], b5["second"]
    print(f"  median entry date: {b5['median_date'].date()}")
    print(
        f"  first half : n={f['n']}  WR={f['win_rate']}%  PF={f['profit_factor']:.3f}  "
        f"avg={f['avg_net_pp']:+.3f}pp"
    )
    print(
        f"  second half: n={s['n']}  WR={s['win_rate']}%  PF={s['profit_factor']:.3f}  "
        f"avg={s['avg_net_pp']:+.3f}pp"
    )

    print("\n" + "=" * 80)
    print("CAVEATS")
    print("=" * 80)
    print("  - Survivorship bias: current BIST30 members backtested over 2y;")
    print("    delisted/demoted tickers are absent (point-in-time universe deferred).")
    print("  - Single 2y window (~500 bars); not a multi-decade sample.")
    print("  - Yahoo Finance data quality (one split anomaly auto-skipped in KONTR).")


if __name__ == "__main__":
    main()
