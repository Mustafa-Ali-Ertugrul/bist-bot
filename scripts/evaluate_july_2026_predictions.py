"""Per-signal prediction-accuracy evaluation over a date window.

Answers: "How accurately does the bot predict?" — for every buy signal generated
inside the window, simulate the trade forward (max N BIST trading days) and
record the net outcome after realised-cost assumptions.

Window selection: ``--month YYYY-MM`` (single month) or explicit
``--start/--end YYYY-MM-DD`` bounds; by default the whole cached history is
evaluated.

No-lookahead guarantee: signals come from ``Backtester._precalculate_signals``,
which scores each row using only ``df.iloc[:i+1]`` and then shifts scores by one
bar. A post-shift ``enter_signal`` at row ``i`` therefore means "decided at the
close of bar i-1, executed at the open of bar i" — the same next-open fill model
the engine itself uses.

Exit simulation mirrors the engine exactly:
- entry bar: gap checks (STOP_GAP/TARGET_GAP at open), then intrabar stop/target
  with the conservative both-hit rule (STOP_LOSS wins)
- later bars: shifted exit_signal at open first (SIGNAL_OPEN), then the same
  gap/intrabar checks against the position's fixed stop/target (no trailing)
- otherwise force-close at the close of bar ``i + max_hold - 1`` (MAX_HOLD).

Costs are a clean single-pass model ( commission + exchange on both sides,
stamp tax + BSMV sell-side only, plus slippage + half-spread price impact per
side ). Defaults come from ``CostModel`` — the engine's own bps values — but the
spread is applied ONCE instead of being double-counted (known P0-A engine bug).
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_walk_forward_bist30 import (  # noqa: E402
    BIST30_TICKERS,
    DEFAULT_CACHE_DIR,
    _cache_path,
    _load_csv_fallback,
    _load_tickers_file,
    _normalize_ohlcv,
)

from bist_bot.backtest.engine import Backtester  # noqa: E402
from bist_bot.backtest.models import CostModel  # noqa: E402
from bist_bot.config import settings  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.regime import (  # noqa: E402
    MarketRegime,
    load_macro_regime_series,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    base = CostModel()
    parser = argparse.ArgumentParser(
        description="Evaluate per-signal prediction accuracy over a date window."
    )
    parser.add_argument("--month", type=str, default=None, help="YYYY-MM single-month window")
    parser.add_argument(
        "--start", type=str, default=None, help="Window start YYYY-MM-DD (default: data start)"
    )
    parser.add_argument(
        "--end", type=str, default=None, help="Window end YYYY-MM-DD (default: data end)"
    )
    parser.add_argument(
        "--max-hold",
        type=int,
        default=5,
        help="Max holding period incl. entry bar, in trading days (default 5)",
    )
    parser.add_argument("--notional", type=float, default=100_000.0, help="TL per signal")
    parser.add_argument(
        "--profile",
        type=str,
        default="conservative",
        choices=("conservative", "research_v1"),
    )
    parser.add_argument("--buy-threshold", type=float, default=None)
    parser.add_argument("--target-rr", type=float, default=2.0)
    parser.add_argument("--commission-bps", type=float, default=base.commission_bps)
    parser.add_argument("--exchange-bps", type=float, default=base.exchange_fee_bps)
    parser.add_argument("--stamp-bps", type=float, default=base.stamp_tax_bps)
    parser.add_argument("--bsmv-bps", type=float, default=base.bsmv_bps)
    parser.add_argument(
        "--spread-bps",
        type=float,
        default=base.spread_bps,
        help="Half-spread applied per side as price impact (CostModel convention)",
    )
    parser.add_argument("--slippage-bps", type=float, default=base.fixed_slippage_bps)
    parser.add_argument("--cache-dir", type=str, default=str(DEFAULT_CACHE_DIR))
    parser.add_argument(
        "--output", type=str, default=None, help="CSV path (default derived from window)"
    )
    parser.add_argument("--limit", type=int, default=0, help="First N tickers (smoke test)")
    parser.add_argument(
        "--tickers-file",
        type=str,
        default=None,
        help=(
            "CSV file with a 'ticker' column to use as the universe "
            "instead of BIST30 (e.g. BIST100 expansion)."
        ),
    )
    parser.add_argument(
        "--macro-regime-mode",
        type=str,
        default="off",
        choices=("off", "observe", "enforce"),
        help=(
            "Deney D: macro regime entry gate. Applied inside "
            "Backtester._precalculate_signals (no duplicated gate logic). "
            "Benchmarks are loaded cache-only from --cache-dir."
        ),
    )
    parser.add_argument(
        "--sideways-mult",
        type=float,
        default=None,
        help=(
            "Deney G: override sideways_score_multiplier on the profile "
            "(e.g. 1.0 disables the sideways score penalty)."
        ),
    )
    parser.add_argument(
        "--stop-atr-mult",
        type=float,
        default=None,
        help=(
            "Deney O: override the ATR stop multiplier used for "
            "stop_loss_atr (indicators default is 2.0)."
        ),
    )
    parser.add_argument(
        "--trailing-atr-mult",
        type=float,
        default=None,
        help=(
            "Deney M: enable an ATR trailing stop (k * ATR below the peak "
            "close) in the exit simulation. Default: fixed stop."
        ),
    )
    parser.add_argument(
        "--pv-confirmation-required",
        action="store_true",
        help=(
            "Deney F: require price_volume_direction == BULLISH_CONFIRMATION "
            "for long entries (opt-in; default preserves current behaviour)."
        ),
    )
    return parser.parse_args(argv)


def _load_cached(ticker: str, cache_dir: Path, period: str = "3y") -> pd.DataFrame | None:
    path = _cache_path(cache_dir, ticker, period)
    if path.exists():
        try:
            return _normalize_ohlcv(pd.read_parquet(path))
        except Exception:
            pass
    return _load_csv_fallback(cache_dir, ticker, period)


def _intrabar_exit(
    stop: float, target: float, o: float, h: float, low: float
) -> tuple[str, float] | None:
    """Mirror of Backtester._simulate_intrabar_exit (reference prices)."""
    if stop > 0 and o <= stop:
        return "STOP_GAP", o
    if target > 0 and o >= target:
        return "TARGET_GAP", o
    stop_hit = stop > 0 and low <= stop
    target_hit = target > 0 and h >= target
    if stop_hit and target_hit:
        return "STOP_LOSS", stop
    if stop_hit:
        return "STOP_LOSS", stop
    if target_hit:
        return "TAKE_PROFIT", target
    return None


def evaluate_ticker(
    ticker: str,
    df: pd.DataFrame,
    backtester: Backtester,
    *,
    month_start: pd.Timestamp | None,
    month_end: pd.Timestamp | None,
    max_hold: int,
    notional: float,
    cost: CostModel,
    stop_atr_mult: float | None = None,
    trailing_atr_mult: float | None = None,
) -> tuple[list[dict[str, object]], dict[str, float]]:
    enriched = backtester.indicators.add_all(df)
    if stop_atr_mult is not None and "atr" in enriched.columns:
        # Deney O: recompute the ATR stop with a custom multiplier. The
        # backtester's _precalculate_signals maps stop_loss_atr ->
        # calculated_stop, so overriding the column is sufficient.
        enriched["stop_loss_atr"] = enriched["close"] - (stop_atr_mult * enriched["atr"])
    enriched = enriched.dropna(subset=["rsi", f"sma_{settings.SMA_SLOW}"])
    if len(enriched) < 3:
        return [], {"month_max_score": 0.0, "month_min_score": 0.0}
    sig = backtester._precalculate_signals(enriched)
    if getattr(sig.index, "tz", None) is not None:
        sig = sig.tz_localize(None)

    dates = sig.index
    opens = sig["open"].to_numpy(dtype=float)
    highs = sig["high"].to_numpy(dtype=float)
    lows = sig["low"].to_numpy(dtype=float)
    closes = sig["close"].to_numpy(dtype=float)
    enters = sig["enter_signal"].to_numpy(dtype=bool)
    exits = sig["exit_signal"].to_numpy(dtype=bool)
    stops = sig["calculated_stop"].to_numpy(dtype=float)
    targets = sig["target_price"].to_numpy(dtype=float)
    scores = sig["score"].to_numpy(dtype=float)
    atrs = sig["atr"].to_numpy(dtype=float) if "atr" in sig.columns else np.full(len(sig), np.nan)
    n = len(sig)

    slippage_bps = cost.fixed_slippage_bps
    # CostModel docs define spread_bps as the HALF-spread, applied once per
    # side as price impact (unlike the engine, which double-counts it).
    price_impact = (slippage_bps + cost.spread_bps) / 10_000
    buy_fee_rate = (cost.commission_bps + cost.exchange_fee_bps) / 10_000
    sell_fee_rate = (
        cost.commission_bps + cost.exchange_fee_bps + cost.stamp_tax_bps + cost.bsmv_bps
    ) / 10_000

    mask = np.ones(n, dtype=bool)
    if month_start is not None:
        mask &= dates >= month_start
    if month_end is not None:
        mask &= dates <= month_end
    month_scores = scores[mask]
    diag = {
        "month_max_score": float(month_scores.max()) if len(month_scores) else 0.0,
        "month_min_score": float(month_scores.min()) if len(month_scores) else 0.0,
    }

    rows: list[dict[str, object]] = []
    for i in range(1, n):
        if not enters[i]:
            continue
        date_i = dates[i]
        if month_start is not None and date_i < month_start:
            continue
        if month_end is not None and date_i > month_end:
            continue
        entry_open = float(opens[i])
        stop = float(stops[i])
        target = float(targets[i])

        exit_idx: int | None = None
        reason: str | None = None
        ref: float | None = None

        same_bar = _intrabar_exit(stop, target, opens[i], highs[i], lows[i])
        if same_bar is not None:
            exit_idx, reason, ref = i, same_bar[0], same_bar[1]
        else:
            last_bar = min(i + max_hold - 1, n - 1)
            # Deney M: optional ATR trailing stop from the peak close. The
            # stop for bar j is updated with bar j-1's close/atr (no
            # look-ahead), mirroring diagnose_signal_edge.simulate_exit.
            # With trailing_atr_mult=None cur_stop never rises: the loop
            # then behaves exactly like the original fixed-stop loop.
            peak = closes[i]
            cur_stop = stop

            def _trail_update(k: int) -> None:
                nonlocal peak, cur_stop
                peak = max(peak, closes[k])
                if trailing_atr_mult is not None and not np.isnan(atrs[k]):
                    cur_stop = max(cur_stop, peak - trailing_atr_mult * atrs[k])

            _trail_update(i)
            for j in range(i + 1, last_bar + 1):
                _trail_update(j - 1)
                if exits[j]:
                    exit_idx, reason, ref = j, "SIGNAL_OPEN", float(opens[j])
                    break
                ev = _intrabar_exit(cur_stop, target, float(opens[j]), highs[j], lows[j])
                if ev is not None:
                    exit_idx, reason, ref = j, ev[0], ev[1]
                    break
            if exit_idx is None:
                if i + max_hold - 1 <= n - 1:
                    exit_idx = i + max_hold - 1
                    reason = "MAX_HOLD"
                    ref = float(closes[exit_idx])
                else:
                    rows.append(
                        {
                            "ticker": ticker,
                            "signal_date": str(dates[i - 1].date()),
                            "entry_date": str(dates[i].date()),
                            "score": round(float(scores[i]), 2),
                            "exit_reason": "INCOMPLETE",
                            "complete": False,
                        }
                    )
                    continue

        assert reason is not None and ref is not None and exit_idx is not None

        entry_fill = entry_open * (1 + price_impact)
        unit_cost = entry_fill * (1 + buy_fee_rate)
        shares = int(notional / unit_cost) if unit_cost > 0 else 0
        if shares <= 0:
            continue
        entry_cost = shares * entry_fill * (1 + buy_fee_rate)
        exit_fill = float(ref) * (1 - price_impact)
        exit_proceeds = shares * exit_fill * (1 - sell_fee_rate)
        net_pnl = exit_proceeds - entry_cost
        net_pct = net_pnl / entry_cost * 100.0
        gross_pct = (float(ref) / entry_open - 1.0) * 100.0
        rows.append(
            {
                "ticker": ticker,
                "signal_date": str(dates[i - 1].date()),
                "entry_date": str(dates[i].date()),
                "entry_ref": round(entry_open, 4),
                "stop_loss": round(stop, 4),
                "target_price": round(target, 4),
                "score": round(float(scores[i]), 2),
                "exit_date": str(dates[exit_idx].date()),
                "exit_reason": reason,
                "exit_ref": round(float(ref), 4),
                "bars_held": exit_idx - i + 1,
                "gross_return_pct": round(gross_pct, 3),
                "net_return_pct": round(net_pct, 3),
                "net_pnl_tl": round(net_pnl, 2),
                "win": net_pnl > 0,
                "complete": True,
            }
        )
    return rows, diag


def _wilson_lb(wins: int, n: int, z: float = 1.959964) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / denom
    return max(0.0, centre - half)


def print_summary(
    rows: list[dict[str, object]], args: argparse.Namespace, window_label: str
) -> None:
    done = [r for r in rows if r.get("complete")]
    inc = [r for r in rows if not r.get("complete")]
    print("=" * 92)
    print(
        f"window={window_label}  max_hold={args.max_hold} trading days  "
        f"notional={args.notional:,.0f} TL  profile={args.profile}  "
        f"buy_threshold={args.buy_threshold if args.buy_threshold is not None else 'profile'}"
    )
    print(
        f"costs/side: commission={args.commission_bps}bp exchange={args.exchange_bps}bp "
        f"stamp={args.stamp_bps}bp(sell) bsmv={args.bsmv_bps}bp(sell) "
        f"impact=slippage {args.slippage_bps}bp + half-spread {args.spread_bps:.1f}bp/side "
        "(single-pass; engine's known spread double-count NOT applied)"
    )
    print("-" * 92)
    print(
        f"signals generated in window: {len(rows)}  (complete={len(done)}, incomplete={len(inc)})"
    )
    if not done:
        print("no complete signals")
        return
    wins = sum(1 for r in done if r["win"])
    gross_wins = sum(1 for r in done if float(r["gross_return_pct"]) > 0)
    n = len(done)
    net_pcts = [float(r["net_return_pct"]) for r in done]
    gross_pcts = [float(r["gross_return_pct"]) for r in done]
    print(
        f"NET win rate               : {100 * wins / n:.1f}%  ({wins}/{n})  "
        f"Wilson 95% LB={100 * _wilson_lb(wins, n):.1f}%"
    )
    print(f"gross up-move rate         : {100 * gross_wins / n:.1f}%  ({gross_wins}/{n})")
    print(
        f"mean / median NET return   : {statistics.mean(net_pcts):+.2f}% / {statistics.median(net_pcts):+.2f}%"
    )
    print(
        f"mean / median GROSS return : {statistics.mean(gross_pcts):+.2f}% / {statistics.median(gross_pcts):+.2f}%"
    )
    print(
        f"total net PnL ({args.notional:,.0f} TL/signal): {sum(float(r['net_pnl_tl']) for r in done):+,.0f} TL"
    )
    reasons: dict[str, int] = {}
    reason_wins: dict[str, int] = {}
    for r in done:
        key = str(r["exit_reason"])
        reasons[key] = reasons.get(key, 0) + 1
        reason_wins[key] = reason_wins.get(key, 0) + (1 if r["win"] else 0)
    print("exit reasons:")
    for k in sorted(reasons):
        print(f"  {k:<14}: {reasons[k]:>3}  (net wins: {reason_wins.get(k, 0)})")
    per: dict[str, list[dict[str, object]]] = {}
    for r in done:
        per.setdefault(str(r["ticker"]), []).append(r)
    print("-" * 92)
    print(
        f"{'ticker':<12} {'signals':>7} {'netWR%':>7} {'meanNet%':>9} {'medNet%':>9} {'netPnL':>10}"
    )
    for tk in sorted(per):
        sub = per[tk]
        w = sum(1 for r in sub if r["win"])
        vals = [float(r["net_return_pct"]) for r in sub]
        pnl = sum(float(r["net_pnl_tl"]) for r in sub)
        print(
            f"{tk:<12} {len(sub):>7} {100 * w / len(sub):>6.1f}% "
            f"{statistics.mean(vals):>+8.2f}% {statistics.median(vals):>+8.2f}% {pnl:>+10,.0f}"
        )
    per_month: dict[str, list[dict[str, object]]] = {}
    for r in done:
        per_month.setdefault(str(r["entry_date"])[:7], []).append(r)
    if len(per_month) > 1:
        print("-" * 92)
        print(
            f"{'month':<9} {'signals':>7} {'netWR%':>7} {'meanNet%':>9} {'medNet%':>9} {'netPnL':>10}"
        )
        for mo in sorted(per_month):
            sub = per_month[mo]
            w = sum(1 for r in sub if r["win"])
            vals = [float(r["net_return_pct"]) for r in sub]
            pnl = sum(float(r["net_pnl_tl"]) for r in sub)
            print(
                f"{mo:<9} {len(sub):>7} {100 * w / len(sub):>6.1f}% "
                f"{statistics.mean(vals):>+8.2f}% {statistics.median(vals):>+8.2f}% {pnl:>+10,.0f}"
            )
    print("=" * 92)
    entry_dates = sorted(str(r["entry_date"]) for r in done)
    print(f"entry date range: {entry_dates[0]} .. {entry_dates[-1]}")
    if inc:
        print(f"incomplete signals (no forward data): {', '.join(str(r['ticker']) for r in inc)}")


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "signal_date",
        "entry_date",
        "entry_ref",
        "stop_loss",
        "target_price",
        "score",
        "exit_date",
        "exit_reason",
        "exit_ref",
        "bars_held",
        "gross_return_pct",
        "net_return_pct",
        "net_pnl_tl",
        "win",
        "complete",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.month:
        month_start = pd.Timestamp(f"{args.month}-01")
        month_end = month_start + pd.offsets.MonthEnd(0)
        window_label = args.month
    else:
        month_start = pd.Timestamp(args.start) if args.start else None
        month_end = pd.Timestamp(args.end) if args.end else None
        window_label = f"{args.start or 'data_start'}..{args.end or 'data_end'}"

    params = (
        StrategyParams.research_v1()
        if args.profile == "research_v1"
        else StrategyParams.conservative()
    )
    if args.buy_threshold is not None:
        params.buy_threshold = args.buy_threshold
    if args.sideways_mult is not None:
        params.sideways_score_multiplier = args.sideways_mult
    if args.pv_confirmation_required:
        params.pv_confirmation_required = True

    cost = CostModel(
        commission_bps=args.commission_bps,
        exchange_fee_bps=args.exchange_bps,
        stamp_tax_bps=args.stamp_bps,
        bsmv_bps=args.bsmv_bps,
        spread_bps=args.spread_bps,
        slippage_model="fixed",
        fixed_slippage_bps=args.slippage_bps,
    )
    cache_dir = Path(args.cache_dir)

    macro_series = None
    if args.macro_regime_mode != "off":
        macro_series = load_macro_regime_series(cache_dir)
        print(
            f"macro regime series: {macro_series.index.min().date()} .. "
            f"{macro_series.index.max().date()} "
            f"(BEAR days={int((macro_series == MarketRegime.BEAR).sum())})"
            f" — mode={args.macro_regime_mode}"
        )
    backtester = Backtester(
        strategy_params=params,
        target_rr=args.target_rr,
        cost_model=cost,
        macro_regime_series=macro_series,
        macro_regime_mode=args.macro_regime_mode,
    )

    if args.tickers_file:
        base_tickers = _load_tickers_file(Path(args.tickers_file))
    else:
        base_tickers = BIST30_TICKERS
    tickers = base_tickers[: args.limit] if args.limit > 0 else base_tickers
    all_rows: list[dict[str, object]] = []
    diag_rows: list[tuple[str, float]] = []
    for idx, ticker in enumerate(tickers, start=1):
        df = _load_cached(ticker, cache_dir)
        if df is None or len(df) < 60:
            print(f"[{idx}/{len(tickers)}] {ticker}: no cached data — skipped")
            continue
        if getattr(df.index, "tz", None) is not None:
            df = df.tz_localize(None)
        rows, diag = evaluate_ticker(
            ticker,
            df,
            backtester,
            month_start=month_start,
            month_end=month_end,
            max_hold=max(1, args.max_hold),
            notional=args.notional,
            cost=cost,
            stop_atr_mult=args.stop_atr_mult,
            trailing_atr_mult=args.trailing_atr_mult,
        )
        n_ok = sum(1 for r in rows if r.get("complete"))
        n_all = len(rows)
        last = str(df.index.max().date())
        print(
            f"[{idx}/{len(tickers)}] {ticker}: signals={n_all} (complete={n_ok}) "
            f"month_score_max={diag['month_max_score']:.0f} data->{last}"
        )
        diag_rows.append((ticker, diag["month_max_score"]))
        all_rows.extend(rows)

    print_summary(all_rows, args, window_label)
    if diag_rows:
        ranked = sorted(diag_rows, key=lambda t: t[1], reverse=True)
        print("highest scores in window (how close the bot came to signalling):")
        for tk, s in ranked[:8]:
            print(f"  {tk:<12} max={s:.0f}  (buy threshold = {backtester.buy_threshold:.0f})")
    if args.output:
        out = Path(args.output)
    else:
        tag = window_label.replace("..", "_to_").replace("-", "")
        out = REPO_ROOT / "results" / f"prediction_signals_{tag}.csv"
    write_csv(all_rows, out)
    print(f"CSV written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
