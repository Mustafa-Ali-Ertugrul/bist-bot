"""Round-2 Independent Verification Benchmark (Cross-Model Validation).

This suite was written from scratch with a methodology deliberately
different from the Round-1 stress suite (benchmark_alpha_stress.py).
The trade simulator is re-implemented independently and verified
against the Round-1 engine (TEST 0) before answering five questions
Round-1 did not:

  TEST 0  Replication check     : independent causal sim vs shared causal engine
  TEST 1  Baseline horse race   : Alpha vs XU100 Buy&Hold vs SMA50 timing vs random entries
  TEST 2  Statistical evidence  : t-statistic + bootstrap 95% CI on mean trade return
  TEST 3  Outlier dependency    : remove top-5 / top-10 winners, is the edge still there?
  TEST 4  Stability             : per-ticker breadth + first-half vs second-half
  TEST 5  Execution realism     : lagged-peak (causal) vs same-bar-peak exit logic

The "as-reported" (Round-1 biased) exit variant is retained INSIDE this
file only as the TEST 5 bias-audit reference; all engines consumed by
the research stack are now causal (bist_bot.backtest.alpha_trend_sim).

Run:  $env:PYTHONPATH="src;."; python scripts/benchmark_independent.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scripts.fast_grid_alpha import evaluate, preload_all

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

COST = 0.35  # roundtrip friction, percent (Round-1 base case)
TRAIL = 3.0  # ATR trailing multiplier (Round-1 base case)
STOP_PCT = 4.5  # max initial stop, percent (Round-1 base case)
POS_WEIGHT = 0.20  # fraction of equity per position (Round-1 Monte Carlo convention)
N_RANDOM_SIMS = 200
N_BOOTSTRAP = 10_000
SEED = 42


@dataclass
class VTrade:
    ticker: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    net_pnl_pct: float


@dataclass
class StockData:
    ticker: str
    dates: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    sig: np.ndarray  # entry signal (bool), aligned to dates
    bull: np.ndarray  # benchmark bullish regime (bool), aligned to dates


def prepare_stock(ticker: str, stock: pd.DataFrame, bench: pd.DataFrame) -> StockData:
    """Independently re-compute all indicators for one ticker."""
    s = stock.copy()

    tr = pd.concat(
        [
            s["high"] - s["low"],
            (s["high"] - s["close"].shift(1)).abs(),
            (s["low"] - s["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(14).mean()

    vol_sma20 = s["volume"].rolling(20).mean()
    high_20 = s["high"].rolling(20).max().shift(1)

    rs = s["close"] / bench["close"]
    rs_sma20 = rs.rolling(20).mean()
    rs_sma50 = rs.rolling(50).mean()
    rs_strong = (rs > rs_sma20) & (rs_sma20 > rs_sma50)

    rng = (s["high"] - s["low"]).replace(0, np.nan)
    close_pos = (s["close"] - s["low"]) / rng
    green = (s["close"] > s["open"]) & (close_pos >= 0.65)
    vol_surge = s["volume"] >= (1.4 * vol_sma20)
    breakout = s["close"] >= high_20

    bull = pd.Series(np.asarray(bench["market_bullish"], dtype=bool), index=s.index)
    sig = (bull & rs_strong & vol_surge & breakout & green).fillna(False).astype(bool)

    return StockData(
        ticker=ticker,
        dates=s.index,
        o=s["open"].to_numpy(dtype=float),
        h=s["high"].to_numpy(dtype=float),
        lo=s["low"].to_numpy(dtype=float),
        c=s["close"].to_numpy(dtype=float),
        atr=atr.to_numpy(dtype=float),
        sig=sig.to_numpy(dtype=bool),
        bull=np.asarray(bull, dtype=bool),
    )


def simulate_strategy(sd: StockData, lagged_peak: bool, day0_stop: bool) -> list[VTrade]:
    """Simulate the strategy on one ticker.

    lagged_peak=False replicates the Round-1 exit logic exactly:
    trailing stop derived from the CURRENT bar's close-peak and CURRENT
    ATR, then checked against the CURRENT bar's low (intrabar lookahead).
    lagged_peak=True is causal: the stop is derived only from the
    PREVIOUS bar's close-peak and PREVIOUS ATR.

    day0_stop=True also tests the ENTRY bar's low against the initial
    stop (that stop is known at entry time -> causal). Round-1 never
    checks the entry bar.
    """
    trades: list[VTrade] = []
    in_pos = False
    entry_p = stop_p = peak = 0.0
    entry_i = -1
    n = len(sd.dates)

    for i in range(60, n):
        op, lo, cl = sd.o[i], sd.lo[i], sd.c[i]

        if in_pos:
            if lagged_peak:
                eff = max(stop_p, peak - TRAIL * sd.atr[i - 1])
            else:
                eff = max(stop_p, max(peak, cl) - TRAIL * sd.atr[i])

            if lo <= eff:
                exit_p = min(op, eff)
                net = (exit_p - entry_p) / entry_p * 100.0 - COST
                trades.append(VTrade(sd.ticker, sd.dates[entry_i], sd.dates[i], net))
                in_pos = False
            elif cl > peak:
                peak = cl

        elif sd.sig[i - 1] and not np.isnan(sd.atr[i - 1]):
            entry_p = op
            stop_p = max(entry_p - 1.5 * sd.atr[i - 1], entry_p * (1.0 - STOP_PCT / 100.0))
            if (entry_p - stop_p) / entry_p < 0.015:
                stop_p = entry_p * 0.985
            in_pos = True
            peak = entry_p
            entry_i = i
            if day0_stop and lo <= stop_p:
                net = (stop_p - entry_p) / entry_p * 100.0 - COST
                trades.append(VTrade(sd.ticker, sd.dates[entry_i], sd.dates[i], net))
                in_pos = False

    if in_pos:
        cl_last = sd.c[-1]
        net = (cl_last - entry_p) / entry_p * 100.0 - COST
        trades.append(VTrade(sd.ticker, sd.dates[entry_i], sd.dates[-1], net))

    return trades


def simulate_from_entry(sd: StockData, i_entry: int, conservative: bool = True) -> float | None:
    """Enter at the open of bar i_entry, run the same exit engine."""
    op = sd.o[i_entry]
    if np.isnan(op) or op <= 0 or np.isnan(sd.atr[i_entry - 1]):
        return None

    stop_p = max(op - 1.5 * sd.atr[i_entry - 1], op * (1.0 - STOP_PCT / 100.0))
    if (op - stop_p) / op < 0.015:
        stop_p = op * 0.985
    peak = op

    for j in range(i_entry, len(sd.dates)):
        lo, cl = sd.lo[j], sd.c[j]
        if conservative:
            eff = max(stop_p, peak - TRAIL * sd.atr[j - 1])
        else:
            eff = max(stop_p, max(peak, cl) - TRAIL * sd.atr[j])
        if lo <= eff:
            exit_p = min(sd.o[j], eff)
            return (exit_p - op) / op * 100.0 - COST
        if cl > peak:
            peak = cl

    return (sd.c[-1] - op) / op * 100.0 - COST


def pf_of(pnls: list[float]) -> float:
    wins = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p <= 0))
    return wins / losses if losses > 0 else float("inf")


def stats_of(pnls: list[float]) -> dict[str, float]:
    arr = np.asarray(pnls, dtype=float)
    if len(arr) == 0:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "mean": 0.0, "median": 0.0}
    return {
        "n": len(arr),
        "wr": round(float(np.mean(arr > 0)) * 100.0, 1),
        "pf": round(pf_of(list(arr)), 3),
        "mean": round(float(arr.mean()), 3),
        "median": round(float(np.median(arr)), 3),
    }


def equity_curve(trades: list[VTrade], weight: float = POS_WEIGHT) -> tuple[float, float]:
    """Compound trades sequentially by exit date at fixed position weight."""
    eq = 1.0
    peak_eq = 1.0
    mdd = 0.0
    for tr in sorted(trades, key=lambda x: x.exit_date):
        eq *= 1.0 + (tr.net_pnl_pct / 100.0) * weight
        peak_eq = max(peak_eq, eq)
        mdd = max(mdd, (peak_eq - eq) / peak_eq)
    return (eq - 1.0) * 100.0, mdd * 100.0


def main() -> None:
    print("=" * 80)
    print("ROUND-2 INDEPENDENT VERIFICATION BENCHMARK")
    print("(fresh simulator, methodology independent of the Round-1 stress suite)")
    print("=" * 80)

    print("\nLoading 2y BIST30 data (network fetch)...")
    xu100, cache = preload_all(BIST30_TICKERS, period="2y")
    print(f"Loaded {len(cache)}/30 tickers + XU100 benchmark.")

    prepared: dict[str, StockData] = {}
    for t, df in cache.items():
        common = df.index.intersection(xu100.index)
        if len(common) < 70:
            continue
        prepared[t] = prepare_stock(t, df.loc[common], xu100.loc[common])

    print(
        f"Window: {xu100.index.min().date()} -> {xu100.index.max().date()} | "
        f"bull bars: {int(xu100['market_bullish'].sum())}/{len(xu100)}"
    )

    cons_trades: list[VTrade] = []
    for sd in prepared.values():
        cons_trades.extend(simulate_strategy(sd, lagged_peak=True, day0_stop=True))

    cons = stats_of([t.net_pnl_pct for t in cons_trades])

    # ------------------------------------------------------------------
    # TEST 0: Replication check
    # ------------------------------------------------------------------
    ref = evaluate(xu100, cache, TRAIL, STOP_PCT, COST)
    print("\n" + "=" * 80)
    print("TEST 0: REPLICATION CHECK (independent causal sim vs shared causal engine)")
    print("=" * 80)
    print(f"  {'metric':<16} {'independent sim':>18} {'shared engine':>18}")
    rows = [
        ("n", cons["n"], ref["n"]),
        ("win_rate %", cons["wr"], ref["win_rate"]),
        ("profit_factor", cons["pf"], ref["profit_factor"]),
        ("avg_net_pp", cons["mean"], ref["avg_net_pp"]),
    ]
    for label, mine, theirs in rows:
        print(f"  {label:<16} {mine:>18} {theirs:>18}")
    match = cons["n"] == ref["n"] and abs(cons["pf"] - ref["profit_factor"]) < 0.01
    print(f"  --> {'REPLICATION VERIFIED' if match else 'MISMATCH - INVESTIGATE'}")

    # ------------------------------------------------------------------
    # TEST 1: Baseline horse race
    # ------------------------------------------------------------------
    strat_pnls = np.array([t.net_pnl_pct for t in cons_trades])
    rng = np.random.default_rng(SEED)

    pool: list[tuple[str, int]] = []
    for t, sd in prepared.items():
        for i in range(60, len(sd.dates) - 1):
            if sd.bull[i - 1] and not np.isnan(sd.atr[i - 1]):
                pool.append((t, i))

    sim_means: list[float] = []
    sim_pfs: list[float] = []
    for _ in range(N_RANDOM_SIMS):
        picks = rng.integers(0, len(pool), size=len(cons_trades))
        pnls: list[float] = []
        for k in picks:
            t, i = pool[int(k)]
            r = simulate_from_entry(prepared[t], int(i))
            if r is not None:
                pnls.append(r)
        if pnls:
            sim_means.append(float(np.mean(pnls)))
            sim_pfs.append(pf_of(pnls))

    sim_means_arr = np.array(sim_means)
    sim_pfs_arr = np.array(sim_pfs)

    px = xu100["close"].dropna()
    eq_bh = px / px.iloc[0]
    bh_total = (eq_bh.iloc[-1] - 1.0) * 100.0
    bh_mdd = float(((eq_bh.cummax() - eq_bh) / eq_bh.cummax()).max() * 100.0)

    pos = (xu100["close"] > xu100["sma50"]).astype(float).shift(1).fillna(0.0)
    daily = xu100["close"].pct_change().fillna(0.0)
    turn = pos.diff().abs().fillna(0.0)
    r_sma = pos * daily - turn * (COST / 100.0)
    eq_sma = (1.0 + r_sma).cumprod()
    sma_total = (eq_sma.iloc[-1] - 1.0) * 100.0
    sma_mdd = float(((eq_sma.cummax() - eq_sma) / eq_sma.cummax()).max() * 100.0)

    strat_total, strat_mdd = equity_curve(cons_trades)

    print("\n" + "=" * 80)
    print("TEST 1: BASELINE HORSE RACE (causal exits, 20% position weight)")
    print("=" * 80)
    print(f"  {'approach':<34} {'total ret %':>11} {'maxDD %':>8} {'PF':>7} {'mean pp':>9}")
    print(
        f"  {'Alpha Trend (causal exits)':<34} {strat_total:>+11.1f} {strat_mdd:>8.1f} "
        f"{cons['pf']:>7.3f} {cons['mean']:>+9.3f}"
    )
    print(
        f"  {'Random entries (median of 200)':<34} {'--':>11} {'--':>8} "
        f"{np.median(sim_pfs_arr):>7.3f} {np.median(sim_means_arr):>+9.3f}"
    )
    print(f"  {'XU100 Buy & Hold':<34} {bh_total:>+11.1f} {bh_mdd:>8.1f} {'--':>7} {'--':>9}")
    print(f"  {'XU100 SMA50 timing':<34} {sma_total:>+11.1f} {sma_mdd:>8.1f} {'--':>7} {'--':>9}")
    pct = 100.0 * float(np.mean(sim_means_arr >= cons["mean"]))
    print(
        f"\n  Random-entry mean distribution: p5 {np.percentile(sim_means_arr, 5):+.3f} | "
        f"median {np.median(sim_means_arr):+.3f} | p95 {np.percentile(sim_means_arr, 95):+.3f} pp"
    )
    print(
        f"  Random-entry PF distribution  : p5 {np.percentile(sim_pfs_arr, 5):.3f} | "
        f"median {np.median(sim_pfs_arr):.3f} | p95 {np.percentile(sim_pfs_arr, 95):.3f}"
    )
    print(f"  --> Strategy mean sits at the {pct:.1f} percentile of the random-entry distribution")

    # ------------------------------------------------------------------
    # TEST 2: Statistical evidence
    # ------------------------------------------------------------------
    arr = strat_pnls
    n = len(arr)
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1))
    tstat = mean / (sd / math.sqrt(n))
    p_two = math.erfc(abs(tstat) / math.sqrt(2))
    boot = rng.choice(arr, size=(N_BOOTSTRAP, n), replace=True).mean(axis=1)
    lo_ci, hi_ci = np.percentile(boot, [2.5, 97.5])

    print("\n" + "=" * 80)
    print("TEST 2: STATISTICAL EVIDENCE (causal trade returns)")
    print("=" * 80)
    print(f"  n={n}  mean={mean:+.3f}pp  sd={sd:.3f}pp  median={np.median(arr):+.3f}pp")
    print(f"  t-statistic={tstat:.3f}  two-sided p (normal approx)={p_two:.4f}")
    print(f"  bootstrap 95% CI of mean: [{lo_ci:+.3f}, {hi_ci:+.3f}] pp  ({N_BOOTSTRAP} resamples)")
    sig = p_two < 0.05 and lo_ci > 0
    print(
        f"  --> {'Mean significantly above zero at 5% level' if sig else 'NOT significant at 5% level'}"
    )

    # ------------------------------------------------------------------
    # TEST 3: Outlier dependency
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 3: OUTLIER DEPENDENCY")
    print("=" * 80)
    srt = np.sort(arr)[::-1]
    for k in (0, 5, 10):
        trimmed = srt[k:]
        st = stats_of(list(trimmed))
        label = "full sample" if k == 0 else f"excluding top-{k} winners"
        print(
            f"  {label:<26} n={st['n']:<4} PF={st['pf']:>6.3f}  mean={st['mean']:>+7.3f}pp  "
            f"win%={st['wr']:.1f}"
        )
    gross_wins = float(arr[arr > 0].sum())
    top5 = float(srt[:5].sum())
    print(
        f"  top-5 winners contribute {top5:+.1f}pp = {top5 / max(gross_wins, 1e-9) * 100:.0f}% "
        f"of all gross wins ({gross_wins:+.1f}pp); net total of all trades {float(arr.sum()):+.1f}pp"
    )

    # ------------------------------------------------------------------
    # TEST 4: Stability (breadth & time consistency)
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 4: STABILITY (per-ticker breadth & time split)")
    print("=" * 80)
    by_ticker: dict[str, float] = {}
    for tr in cons_trades:
        by_ticker[tr.ticker] = by_ticker.get(tr.ticker, 0.0) + tr.net_pnl_pct
    pos_tickers = sum(1 for v in by_ticker.values() if v > 0)
    best = max(by_ticker.items(), key=lambda kv: kv[1])
    worst = min(by_ticker.items(), key=lambda kv: kv[1])
    print(f"  Ticker breadth: {pos_tickers}/{len(by_ticker)} tickers net positive")
    print(f"  best: {best[0]} {best[1]:+.1f}pp | worst: {worst[0]} {worst[1]:+.1f}pp")

    dates_sorted = sorted(tr.entry_date for tr in cons_trades)
    median_date = dates_sorted[len(dates_sorted) // 2]
    h1 = [tr.net_pnl_pct for tr in cons_trades if tr.entry_date < median_date]
    h2 = [tr.net_pnl_pct for tr in cons_trades if tr.entry_date >= median_date]
    s1, s2 = stats_of(h1), stats_of(h2)
    print(
        f"  First half (entry < {median_date.date()}): n={s1['n']}  PF={s1['pf']:.3f}  "
        f"mean={s1['mean']:+.3f}pp"
    )
    print(
        f"  Second half                        : n={s2['n']}  PF={s2['pf']:.3f}  "
        f"mean={s2['mean']:+.3f}pp"
    )

    # ------------------------------------------------------------------
    # TEST 5: Execution realism audit (bias decomposition)
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 5: EXECUTION REALISM (intrabar lookahead audit, bias decomposition)")
    print("=" * 80)
    combos = [
        ("as-reported (Round-1)", False, False),
        ("lagged peak only", True, False),
        ("day-0 stop check only", False, True),
        ("fully causal (both)", True, True),
    ]
    print(f"  {'variant':<26} {'n':>4} {'PF':>7} {'mean pp':>9} {'win%':>6}")
    results5: dict[str, dict] = {}
    for label, lp, d0 in combos:
        tr5: list[VTrade] = []
        for sd in prepared.values():
            tr5.extend(simulate_strategy(sd, lagged_peak=lp, day0_stop=d0))
        st5 = stats_of([t.net_pnl_pct for t in tr5])
        results5[label] = st5
        print(
            f"  {label:<26} {st5['n']:>4} {st5['pf']:>7.3f} {st5['mean']:>+9.3f} {st5['wr']:>6.1f}"
        )
    r_rep = results5["as-reported (Round-1)"]
    r_cau = results5["fully causal (both)"]
    if r_rep["pf"] > 0:
        print(
            f"  --> Total bias: PF {r_rep['pf']:.3f} -> {r_cau['pf']:.3f} "
            f"({(r_cau['pf'] / r_rep['pf'] - 1) * 100:+.1f}%), "
            f"mean {r_rep['mean']:+.3f} -> {r_cau['mean']:+.3f} pp"
        )

    print("\n" + "=" * 80)
    print("CAVEATS")
    print("=" * 80)
    print("  - Survivorship bias: current BIST30 members backtested over 2y;")
    print("    delisted/demoted tickers are absent (inflates all results somewhat).")
    print("  - Single 2y window (~500 bars, ~69 trades); not a multi-decade sample.")
    print("  - Yahoo Finance data quality (one split anomaly auto-skipped in KONTR).")


if __name__ == "__main__":
    main()
