"""Retail subscriber economics simulation.

Given a per-signal evaluation CSV (evaluate_july_2026_predictions.py output),
simulate what a retail subscriber would experience following every signal with
the bot's real sizing rules: fixed TL per position, max N concurrent positions,
skip-when-full. Prints monthly PnL distribution, subscription break-even fees,
and concentration stats.

Usage:
    uv run python -X utf8 scripts/retail_economics.py results/prediction_signals_expF_pv_gate.csv
    uv run python -X utf8 scripts/retail_economics.py <csv> --capital 100000 --position-tl 20000 --max-open 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def simulate_portfolio(
    df: pd.DataFrame,
    *,
    position_tl: float,
    max_open: int,
    rank_by: str = "fifo",
    sizing: str = "fixed",
    risk_budget_tl: float = 0.0,
    position_cap_tl: float = 0.0,
    market_scale: pd.Series | None = None,
) -> tuple[pd.DataFrame, int]:
    """Concurrency-limited portfolio sim. Returns (taken_df, skipped_full_count).

    rank_by="fifo": signals are taken in entry_date order (current behaviour).
    rank_by="score": within each entry_date, when fewer slots are free than
    candidates, the highest-``score`` candidates are taken first. This models a
    subscriber who picks the top-scored signals of the day when capital slots
    are limited (cross-day staleness is not modelled: skipped signals expire).

    sizing="fixed": every position is ``position_tl`` (default).
    sizing="risk": risk-parity, mirroring the live bot (risk/sizing.py):
    position_tl_i = min(risk_budget_tl / stop_distance_pct_i, position_cap_tl)
    where stop_distance_pct_i = (entry_ref - stop_loss) / entry_ref. Signals
    with a non-positive stop distance are skipped (live bot sizes them 0 too).

    market_scale: optional Series indexed by date -> float multiplier applied
    to the final position size on that entry date (Deney L market-level
    vol targeting). scale=0 blocks entries that day.
    """
    df = df[df.complete].sort_values("entry_date").reset_index(drop=True)
    open_exits: list[pd.Timestamp] = []
    taken, skipped_full = [], 0
    for _, day in df.groupby("entry_date", sort=True):
        entry_date = day.entry_date.iloc[0]
        day_scale = 1.0
        if market_scale is not None:
            day_scale = float(market_scale.get(entry_date.normalize(), 1.0))
        open_exits = [d for d in open_exits if d > entry_date]
        candidates = day.sort_values("score", ascending=False) if rank_by == "score" else day
        for _, r in candidates.iterrows():
            if len(open_exits) >= max_open:
                skipped_full += 1
                continue
            pos_tl = position_tl
            if sizing == "risk":
                stop_dist_pct = (r.entry_ref - r.stop_loss) / r.entry_ref if r.entry_ref else 0.0
                if stop_dist_pct <= 0:
                    continue
                pos_tl = min(risk_budget_tl / stop_dist_pct, position_cap_tl)
            pos_tl *= day_scale
            if pos_tl <= 0:
                continue
            open_exits.append(r.exit_date)
            taken.append({**r.to_dict(), "position_tl": pos_tl})
    t = pd.DataFrame(taken)
    if len(t):
        t["pnl_tl"] = t.position_tl * t.net_return_pct / 100.0
        t["month"] = t.exit_date.dt.to_period("M")
    return t, skipped_full


def monthly_series(t: pd.DataFrame) -> pd.Series:
    monthly = t.groupby("month").pnl_tl.sum()
    full_idx = pd.period_range(
        t.exit_date.min().to_period("M"), t.exit_date.max().to_period("M"), freq="M"
    )
    return monthly.reindex(full_idx, fill_value=0.0)


def render_report(
    df: pd.DataFrame,
    t: pd.DataFrame,
    monthly: pd.Series,
    skipped_full: int,
    *,
    capital: float,
    position_tl: float,
    max_open: int,
    fees: tuple[float, ...],
    rank_by: str = "fifo",
    sizing: str = "fixed",
) -> str:
    lines: list[str] = []
    a = lines.append
    n_months = len(monthly)
    eq = monthly.cumsum()
    dd = (eq - eq.cummax()).min()
    a("=" * 64)
    a(f"PER-SIGNAL ({len(df)} sinyal, {n_months} ay)")
    a(f"  sinyal/ay (ham)        : {len(df) / n_months:.1f}")
    a(f"  alinan / dolu-atlanan  : {len(t)} / {skipped_full}")
    a(f"  WR                     : %{100 * t.win.mean():.1f}")
    a(f"  ort. net getiri/trade  : %{t.net_return_pct.mean():.3f}")
    a("-" * 64)
    a(
        f"PERAKENDE SIM (sermaye {capital:,.0f} TL, pozisyon {position_tl:,.0f} TL, max {max_open} acik, secim={rank_by}, sizing={sizing})"
    )
    a(f"  toplam net PnL         : {t.pnl_tl.sum():+,.0f} TL / {n_months} ay")
    a(f"  aylik ort.             : {monthly.mean():+,.0f} TL")
    a(f"  aylik medyan           : {monthly.median():+,.0f} TL")
    a(
        f"  pozitif ay orani       : %{100 * (monthly > 0).mean():.0f} ({int((monthly > 0).sum())}/{n_months})"
    )
    a(f"  en kotu ay             : {monthly.min():+,.0f} TL ({monthly.idxmin()})")
    a(f"  en iyi ay              : {monthly.max():+,.0f} TL ({monthly.idxmax()})")
    a(f"  realized equity max DD : {dd:+,.0f} TL")
    a(f"  toplam getiri          : %{100 * t.pnl_tl.sum() / capital:+.1f} / {n_months} ay")
    a("-" * 64)
    a("EN KOTU 5 AY:")
    for m, v in monthly.nsmallest(5).items():
        a(f"  {m}  {v:+,.0f} TL")
    a("-" * 64)
    for fee in fees:
        net = monthly.mean() - fee
        verdict = "abone KAZANIR" if net > 0 else "abone KAYBEDER"
        a(f"  abonelik {fee:>6,.0f} TL/ay -> aboneye kalan {net:+,.0f} TL/ay  [{verdict}]")
    a("=" * 64)
    top = t.groupby("ticker").pnl_tl.sum().sort_values(ascending=False)
    a(
        f"PnL'nin %50'sini ureten hisse sayisi: {(top.cumsum() < top.sum() * 0.5).sum() + 1} / {top.size}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", type=str, help="evaluate_july_2026_predictions.py output CSV")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--position-tl", type=float, default=20_000.0)
    p.add_argument("--max-open", type=int, default=5)
    p.add_argument(
        "--rank-by",
        choices=("fifo", "score"),
        default="fifo",
        help="Selection rule when slots are limited: fifo (arrival order) or "
        "score (highest daily score first).",
    )
    p.add_argument("--fees", type=float, nargs="*", default=(500, 1_000, 1_500, 2_500))
    p.add_argument(
        "--sizing",
        choices=("fixed", "risk"),
        default="fixed",
        help="fixed: every position is --position-tl. risk: risk-parity per "
        "signal (risk_budget / stop_distance), mirroring live sizing.",
    )
    p.add_argument(
        "--risk-budget-tl",
        type=float,
        default=0.0,
        help="TL risked per trade in risk mode (default: 2%% of --capital).",
    )
    p.add_argument(
        "--position-cap-tl",
        type=float,
        default=0.0,
        help="Max TL per position in risk mode (default: = --position-tl).",
    )
    p.add_argument(
        "--market-scale-file",
        type=str,
        default=None,
        help="CSV with date,scale columns (Deney L): position multiplier per "
        "entry date; scale=0 blocks entries that day.",
    )
    p.add_argument("--output", type=str, default=None, help="Write report text to file")
    args = p.parse_args(argv)

    risk_budget = args.risk_budget_tl or 0.02 * args.capital
    position_cap = args.position_cap_tl or args.position_tl

    market_scale = None
    if args.market_scale_file:
        ms = pd.read_csv(args.market_scale_file, parse_dates=["date"])
        market_scale = pd.Series(ms.scale.values, index=ms.date.dt.normalize())

    df = pd.read_csv(args.csv, parse_dates=["signal_date", "entry_date", "exit_date"])
    t, skipped = simulate_portfolio(
        df,
        position_tl=args.position_tl,
        max_open=args.max_open,
        rank_by=args.rank_by,
        sizing=args.sizing,
        risk_budget_tl=risk_budget,
        position_cap_tl=position_cap,
        market_scale=market_scale,
    )
    if not len(t):
        print("No trades taken; nothing to report.", file=sys.stderr)
        return 1
    monthly = monthly_series(t)
    report = render_report(
        df,
        t,
        monthly,
        skipped,
        capital=args.capital,
        position_tl=args.position_tl,
        max_open=args.max_open,
        fees=tuple(args.fees),
        rank_by=args.rank_by,
        sizing=args.sizing,
    )
    print(report)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
        print(f"\nReport written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
