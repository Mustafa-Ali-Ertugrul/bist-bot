"""Deney D: acceptance-criteria decision table for the macro regime gate experiment.

Reads the four experiment artefacts and emits a machine-checked verdict for
every criterion in the plan (section 9) — no hand-computed numbers.

Inputs (defaults under results/):
    - walk-forward CSV: macro observe  (walk_forward_expD_macro_observe.csv)
    - walk-forward CSV: macro enforce  (walk_forward_expD_macro_enforce.csv)
    - per-signal  CSV: macro observe   (prediction_signals_macro_observe.csv)
    - per-signal  CSV: macro enforce   (prediction_signals_macro_enforce.csv)

Usage:
    uv run python scripts/analyze_macro_gate_experiment.py
    uv run python scripts/analyze_macro_gate_experiment.py --wf-observe <csv> ...

Output: invariant checks, strategy criteria table, and a recommendation
(ACCEPT / REJECT / INCONCLUSIVE) per the plan's acceptance rules.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPO_ROOT / "results"

KEY = ("ticker", "signal_date", "entry_date")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wf-observe",
        type=str,
        default=str(DEFAULT_RESULTS / "walk_forward_expD_macro_observe.csv"),
    )
    parser.add_argument(
        "--wf-enforce",
        type=str,
        default=str(DEFAULT_RESULTS / "walk_forward_expD_macro_enforce.csv"),
    )
    parser.add_argument(
        "--signals-observe",
        type=str,
        default=str(DEFAULT_RESULTS / "prediction_signals_macro_observe.csv"),
    )
    parser.add_argument(
        "--signals-enforce",
        type=str,
        default=str(DEFAULT_RESULTS / "prediction_signals_macro_enforce.csv"),
    )
    parser.add_argument(
        "--min-oos-trade-retention",
        type=float,
        default=0.60,
        help="Minimum share of baseline OOS trades that must survive enforce (default 0.60)",
    )
    return parser.parse_args(argv)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "None", "nan", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _ok_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if r.get("status") == "OK"]


def _complete_signals(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if str(r.get("complete")) == "True"]


def _signal_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["ticker"], row["signal_date"], row["entry_date"])


def _wilson_lb(wins: int, n: int, z: float = 1.959964) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / denom
    return max(0.0, centre - half)


def _signal_stats(rows: list[dict[str, str]]) -> dict[str, float]:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "wins": 0,
            "net_wr": 0.0,
            "wilson_lb": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "net_pnl": 0.0,
        }
    wins = sum(1 for r in rows if str(r.get("win")) == "True")
    net = [_f(r.get("net_return_pct")) or 0.0 for r in rows]
    pnl = [_f(r.get("net_pnl_tl")) or 0.0 for r in rows]
    return {
        "n": n,
        "wins": wins,
        "net_wr": wins / n,
        "wilson_lb": _wilson_lb(wins, n),
        "mean": statistics.mean(net),
        "median": statistics.median(net),
        "net_pnl": sum(pnl),
    }


def analyze(args: argparse.Namespace) -> int:
    wf_obs = _read_csv(Path(args.wf_observe))
    wf_enf = _read_csv(Path(args.wf_enforce))
    sig_obs = _complete_signals(_read_csv(Path(args.signals_observe)))
    sig_enf = _complete_signals(_read_csv(Path(args.signals_enforce)))

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append((name, bool(passed), detail))

    # -- Invariants -----------------------------------------------------------
    obs_bars = sum(int(_f(r.get("macro_bear_oos_bars")) or 0) for r in wf_obs)
    enf_bars = sum(int(_f(r.get("macro_bear_oos_bars")) or 0) for r in wf_enf)
    obs_cand = sum(int(_f(r.get("macro_bear_oos_entry_candidates")) or 0) for r in wf_obs)
    enf_cand = sum(int(_f(r.get("macro_bear_oos_entry_candidates")) or 0) for r in wf_enf)
    check(
        "invariant: bear bars & candidates identical in observe/enforce",
        obs_bars == enf_bars and obs_cand == enf_cand,
        f"bars {obs_bars} vs {enf_bars}; candidates {obs_cand} vs {enf_cand}",
    )

    obs_keys = {_signal_key(r) for r in sig_obs}
    enf_keys = {_signal_key(r) for r in sig_enf}
    enforce_only = enf_keys - obs_keys
    observe_only = obs_keys - enf_keys
    shared = obs_keys & enf_keys
    check(
        "invariant: enforce adds no new signals (enforce-only keys == 0)",
        len(enforce_only) == 0,
        f"enforce-only={len(enforce_only)} observe-only={len(observe_only)} shared={len(shared)}",
    )

    obs_by_key = {_signal_key(r): r for r in sig_obs}
    enf_by_key = {_signal_key(r): r for r in sig_enf}
    mismatches = 0
    for key in shared:
        o, e = obs_by_key[key], enf_by_key[key]
        if (
            _f(o.get("net_return_pct")) != _f(e.get("net_return_pct"))
            or o.get("exit_reason") != e.get("exit_reason")
            or _f(o.get("score")) != _f(e.get("score"))
        ):
            mismatches += 1
    check(
        "invariant: shared keys identical returns/exit/score",
        mismatches == 0,
        f"{mismatches} mismatched shared keys",
    )

    # -- Strategy criteria ----------------------------------------------------
    obs_ok = _ok_rows(wf_obs)
    enf_ok = _ok_rows(wf_enf)
    obs_ret = [_f(r.get("oos_mean_return")) for r in obs_ok]
    enf_ret = [_f(r.get("oos_mean_return")) for r in enf_ok]
    obs_ret_v = [v for v in obs_ret if v is not None]
    enf_ret_v = [v for v in enf_ret if v is not None]
    n = len(obs_ret_v)

    blocked_rows = _complete_signals([obs_by_key[k] for k in sorted(observe_only)])
    blocked = _signal_stats(blocked_rows)
    blocked_pnl = blocked["net_pnl"]

    inconclusive = enf_cand == 0 or len(blocked_rows) == 0

    def share(vals: list[float], pred) -> float:
        return sum(1 for v in vals if pred(v)) / len(vals) if vals else 0.0

    obs_pos = share(obs_ret_v, lambda v: v > 0)
    enf_pos = share(enf_ret_v, lambda v: v > 0)
    check(
        "criterion: positive OOS ticker share >= 21/30 AND not below observe",
        enf_pos >= (21 / 30) and enf_pos >= obs_pos,
        f"observe={obs_pos:.2f} ({sum(1 for v in obs_ret_v if v > 0)}/{n}) "
        f"enforce={enf_pos:.2f} ({sum(1 for v in enf_ret_v if v > 0)}/{len(enf_ret_v)})",
    )

    obs_mean = statistics.mean(obs_ret_v) if obs_ret_v else 0.0
    enf_mean = statistics.mean(enf_ret_v) if enf_ret_v else 0.0
    obs_med = statistics.median(obs_ret_v) if obs_ret_v else 0.0
    enf_med = statistics.median(enf_ret_v) if enf_ret_v else 0.0
    check(
        "criterion: mean & median OOS not worse than observe",
        enf_mean >= obs_mean and enf_med >= obs_med,
        f"mean {obs_mean:+.2f} -> {enf_mean:+.2f}; median {obs_med:+.2f} -> {enf_med:+.2f}",
    )

    obs_dd = [_f(r.get("oos_max_dd")) or 0.0 for r in obs_ok]
    enf_dd = [_f(r.get("oos_max_dd")) or 0.0 for r in enf_ok]
    obs_dd_m = statistics.mean(obs_dd) if obs_dd else 0.0
    enf_dd_m = statistics.mean(enf_dd) if enf_dd else 0.0
    # max_drawdown_pct is negative in the engine; improvement = less negative.
    check(
        "criterion: mean max drawdown improves",
        enf_dd_m >= obs_dd_m,
        f"mean OOS maxDD {obs_dd_m:.2f} -> {enf_dd_m:.2f}",
    )

    obs_overfit = share(
        [1.0 if r.get("has_overfitting_warning") == "True" else 0.0 for r in obs_ok], bool
    )
    enf_overfit = share(
        [1.0 if r.get("has_overfitting_warning") == "True" else 0.0 for r in enf_ok], bool
    )
    check(
        "criterion: overfit share does not increase",
        enf_overfit <= obs_overfit,
        f"observe={obs_overfit:.2f} enforce={enf_overfit:.2f}",
    )

    obs_trades = sum(int(_f(r.get("total_oos_trades")) or 0) for r in wf_obs)
    enf_trades = sum(int(_f(r.get("total_oos_trades")) or 0) for r in wf_enf)
    retention = enf_trades / obs_trades if obs_trades else 1.0
    check(
        "criterion: >= 60-70% of OOS trades retained",
        retention >= args.min_oos_trade_retention,
        f"observe trades={obs_trades} enforce trades={enf_trades} retention={retention:.2f}",
    )

    so = _signal_stats(sig_obs)
    se = _signal_stats(sig_enf)
    check(
        "criterion: per-signal net WR, Wilson LB and total net PnL not worse",
        se["net_wr"] >= so["net_wr"]
        and se["wilson_lb"] >= so["wilson_lb"]
        and se["net_pnl"] >= so["net_pnl"],
        f"WR {so['net_wr']:.2%} -> {se['net_wr']:.2%}; "
        f"WilsonLB {so['wilson_lb']:.2%} -> {se['wilson_lb']:.2%}; "
        f"netPnL {so['net_pnl']:+,.0f} -> {se['net_pnl']:+,.0f} TL",
    )
    check(
        "criterion: blocked signals' total net PnL <= 0 (gate removed losers)",
        blocked_pnl <= 0,
        f"blocked n={blocked['n']} netWR={blocked['net_wr']:.2%} "
        f"mean={blocked['mean']:+.2f}% median={blocked['median']:+.2f}% "
        f"netPnL={blocked_pnl:+,.0f} TL",
    )

    # 2023-10 breakdown for the blocked set (and context for both modes).
    def _month_rows(rows: list[dict[str, str]], month: str) -> list[dict[str, str]]:
        return [r for r in rows if str(r.get("entry_date", "")).startswith(month)]

    oct_obs = _signal_stats(_month_rows(sig_obs, "2023-10"))
    oct_enf = _signal_stats(_month_rows(sig_enf, "2023-10"))

    # -- Report ---------------------------------------------------------------
    print("=" * 100)
    print("DENEY D — MACRO REGIME GATE: acceptance report")
    print("=" * 100)
    print(f"WF observe : {args.wf_observe}")
    print(f"WF enforce : {args.wf_enforce}")
    print(f"SIG observe: {args.signals_observe}  ({len(sig_obs)} complete signals)")
    print(f"SIG enforce: {args.signals_enforce}  ({len(sig_enf)} complete signals)")
    print("-" * 100)
    all_pass = True
    for name, passed, detail in checks:
        mark = "PASS" if passed else "FAIL"
        all_pass = all_pass and passed
        print(f"[{mark}] {name}")
        print(f"       {detail}")
    print("-" * 100)
    print(
        f"2023-10 context — observe: n={oct_obs['n']} netWR={oct_obs['net_wr']:.2%} "
        f"netPnL={oct_obs['net_pnl']:+,.0f} TL | enforce: n={oct_enf['n']} "
        f"netWR={oct_enf['net_wr']:.2%} netPnL={oct_enf['net_pnl']:+,.0f} TL"
    )
    if (
        oct_obs["n"] > 0
        and oct_enf["net_pnl"] > oct_obs["net_pnl"]
        and se["net_pnl"] < so["net_pnl"]
    ):
        print(
            "NOTE: improvement concentrated in 2023-10 while the overall period "
            "degrades — per plan this is a REJECT signal; review the table above."
        )
    print("-" * 100)
    if inconclusive:
        print(
            f"VERDICT: INCONCLUSIVE — bear-day entry candidates={enf_cand}, "
            f"blocked signals={len(blocked_rows)}. No accept/reject decision possible."
        )
    elif all_pass:
        print("VERDICT: ACCEPT — all invariants and strategy criteria pass.")
    else:
        print("VERDICT: REJECT — one or more invariants/criteria failed (see above).")
    print("=" * 100)
    print(
        "Reminder: even on ACCEPT, live/default-profile activation requires a "
        "separate explicit user approval."
    )
    return 0 if (all_pass and not inconclusive) else (2 if inconclusive else 1)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for path in (args.wf_observe, args.wf_enforce, args.signals_observe, args.signals_enforce):
        if not Path(path).exists():
            print(f"missing input: {path}", file=sys.stderr)
            return 1
    return analyze(args)


if __name__ == "__main__":
    sys.exit(main())
