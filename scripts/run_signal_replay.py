"""CLI runner for the historical signal replay backtest.

Replays persisted signals (SQLite by default) on historical daily OHLCV bars
using the conservative exit semantics from the Faz 2 contract:

- Entry: first tradable bar open strictly after the signal date.
- Exit: persisted stop/target levels only (never recomputed); same-bar
  TP+SL collision resolves SL-first; open gaps exit at bar open.
- Timeout: configurable bars (default 5), exits at the last bar close.
- Costs: zero / base / stress scenarios from the shared CostModel.
- Guard: N >= --min-n (default 10) per analysis cell; below that the cell is
  flagged low_n and no threshold recommendation is emitted.

Usage (from repo root):
    python scripts/run_signal_replay.py
    python scripts/run_signal_replay.py --dataset raw,episodes --cost zero,base
    python scripts/run_signal_replay.py --ticker THYAO.IS --out results/thyao.json
    python scripts/run_signal_replay.py --bars-dir path/to/csv --limit 100

Outputs:
    results/signal_replay_summary.json   (summary + buckets + filters + decision)
    results/signal_replay_trades.csv     (one row per dataset x cost trade)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bist_bot.backtest.signal_replay import (
    CONFIDENCE_KEYS,
    ReplaySignal,
    SignalReplayEngine,
    analyze_confidence_buckets,
    analyze_score_buckets,
    build_cost_scenarios,
    build_dataset_episodes,
    build_dataset_first_actionable,
    build_dataset_raw,
    calculate_cell_metrics,
    evaluate_entry_delays,
    evaluate_hysteresis,
    evaluate_indicator_filters,
    generate_decision_report,
    normalize_bars,
)
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.params import StrategyParams

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = REPO_ROOT / "results" / "signal_replay_summary.json"

DATASETS = ("raw", "episodes", "first_actionable")
COST_SCENARIOS = ("zero", "base", "stress")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay persisted signals on historical daily bars (Faz 2).",
    )
    parser.add_argument(
        "--dataset",
        default="all",
        help=f"Comma-separated datasets: {','.join(DATASETS)} or 'all' (default: all)",
    )
    parser.add_argument(
        "--cost",
        default="all",
        help=f"Comma-separated cost scenarios: {','.join(COST_SCENARIOS)} or 'all' (default: all)",
    )
    parser.add_argument("--timeout-bars", type=int, default=5, help="Timeout in bars (default 5)")
    parser.add_argument(
        "--episode-gap-bars",
        type=int,
        default=5,
        help="Max bar gap for signals to remain in one episode (default 5)",
    )
    parser.add_argument("--min-score", type=float, default=0.0, help="Min |score| to include")
    parser.add_argument("--ticker", default=None, help="Restrict to a single ticker")
    parser.add_argument("--limit", type=int, default=5000, help="Max signals to load")
    parser.add_argument("--min-n", type=int, default=10, help="Guard sample size per cell (default 10)")
    parser.add_argument("--out", default=str(DEFAULT_SUMMARY), help="Summary JSON output path")
    parser.add_argument("--trades-out", default=None, help="Trades CSV output path")
    parser.add_argument("--db-path", default=None, help="SQLite database path (default: settings)")
    parser.add_argument(
        "--bars-dir",
        default=None,
        help="Directory of per-ticker OHLCV CSVs for offline replay (no network)",
    )
    parser.add_argument("--period", default="4y", help="History period for the fetcher (default 4y)")
    parser.add_argument("--interval", default="1d", help="Bar interval (default 1d)")
    parser.add_argument("--force-download", action="store_true", help="Bypass fetcher cache")
    return parser.parse_args(argv)


def load_signals(
    args: argparse.Namespace,
) -> list[ReplaySignal]:
    # SQLite-first (Faz 2 scope decision): default to the repo-root DB file so the
    # runner never resolves the Postgres DATABASE_URL from the environment.
    db_path = args.db_path or str(REPO_ROOT / "bist_signals.db")
    manager = DatabaseManager(sqlite_path=db_path)
    repo = SignalsRepository(manager)
    rows = repo.get_signals(limit=args.limit, ticker=args.ticker)
    if not rows:
        print(f"No signals found (limit={args.limit}, ticker={args.ticker or 'all'}).", file=sys.stderr)
        return []

    signals: list[ReplaySignal] = []
    for row in rows:
        try:
            ts = row.get("timestamp")
            timestamp = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            continue
        score = row.get("score")
        signals.append(
            ReplaySignal(
                id=row.get("id", ""),
                ticker=str(row.get("ticker", "")),
                timestamp=timestamp,
                signal_type=str(row.get("signal_type", "")),
                score=float(score) if score is not None else None,
                price=float(row.get("price") or 0.0),
                stop_loss=float(row["stop_loss"]) if row.get("stop_loss") is not None else None,
                target_price=float(row["target_price"]) if row.get("target_price") is not None else None,
                confidence=row.get("confidence"),
                reasons=list(row.get("reasons") or []),
                score_breakdown=dict(row.get("score_breakdown") or {}),
            )
        )

    if args.min_score > 0:
        before = len(signals)
        signals = [
            s for s in signals
            if s.score is not None and abs(s.score) >= args.min_score
        ]
        print(f"min-score filter {args.min_score}: {before} -> {len(signals)} signals")

    # Chronological order (repository returns DESC).
    signals.sort(key=lambda s: s.timestamp)
    return signals


def load_bars_for_tickers(
    tickers: list[str],
    args: argparse.Namespace,
) -> dict[str, pd.DataFrame]:
    bars_by_ticker: dict[str, pd.DataFrame] = {}
    fetcher = None if args.bars_dir else BISTDataFetcher()
    bars_dir = Path(args.bars_dir) if args.bars_dir else None

    for ticker in sorted(set(tickers)):
        if bars_dir is not None:
            csv_path = bars_dir / f"{ticker}.csv"
            if not csv_path.exists():
                print(f"  [skip] no bars file for {ticker}: {csv_path.name}", file=sys.stderr)
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:
                print(f"  [skip] cannot read {csv_path}: {exc}", file=sys.stderr)
                continue
        else:
            try:
                df = fetcher.fetch_single(
                    ticker,
                    period=args.period,
                    interval=args.interval,
                    force=args.force_download,
                )
            except Exception as exc:
                print(f"  [skip] fetch failed for {ticker}: {exc}", file=sys.stderr)
                continue

        normalized = normalize_bars(df)
        if normalized is None or normalized.empty:
            print(f"  [skip] no usable bars for {ticker}", file=sys.stderr)
            continue
        bars_by_ticker[ticker] = normalized

    print(f"Bars loaded for {len(bars_by_ticker)}/{len(set(tickers))} tickers")
    return bars_by_ticker


def params_fingerprint(params: StrategyParams) -> str:
    return json.dumps(
        {
            "buy_threshold": params.buy_threshold,
            "sell_threshold": params.sell_threshold,
            "weak_buy_threshold": params.weak_buy_threshold,
            "weak_sell_threshold": params.weak_sell_threshold,
            "strong_buy_threshold": params.strong_buy_threshold,
            "strong_sell_threshold": params.strong_sell_threshold,
        },
        sort_keys=True,
    )


def _resolve_choices(value: str, available: tuple[str, ...]) -> list[str]:
    if value == "all":
        return list(available)
    out: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if part and part in available:
            out.append(part)
    if not out:
        raise SystemExit(f"Invalid choice(s): {value!r}. Available: {', '.join(available)}")
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    datasets = _resolve_choices(args.dataset, DATASETS)
    costs = _resolve_choices(args.cost, COST_SCENARIOS)

    print("=" * 70)
    print("Faz 2 Signal Replay")
    print(f"  datasets      : {', '.join(datasets)}")
    print(f"  costs         : {', '.join(costs)}")
    print(f"  timeout-bars  : {args.timeout_bars}")
    print(f"  episode-gap   : {args.episode_gap_bars} bars")
    print(f"  min-n guard   : {args.min_n}")
    print("=" * 70)

    signals = load_signals(args)
    if not signals:
        print("Nothing to replay.", file=sys.stderr)
        return 1

    print(f"Loaded {len(signals)} signals across "
          f"{len({s.ticker for s in signals})} tickers")

    bars_by_ticker = load_bars_for_tickers([s.ticker for s in signals], args)
    if not bars_by_ticker:
        print("No bars available; cannot replay.", file=sys.stderr)
        return 1

    params = StrategyParams()
    engine = SignalReplayEngine(
        timeout_bars=args.timeout_bars,
        cost_models=build_cost_scenarios(),
    )

    # ---- Datasets ----
    datasets_map: dict[str, list[ReplaySignal]] = {}
    if "raw" in datasets:
        datasets_map["raw"] = build_dataset_raw(signals)
    if "episodes" in datasets:
        datasets_map["episodes"] = build_dataset_episodes(
            signals, bars_by_ticker, max_gap_bars=args.episode_gap_bars
        )
    if "first_actionable" in datasets:
        datasets_map["first_actionable"] = build_dataset_first_actionable(
            signals, bars_by_ticker, max_gap_bars=args.episode_gap_bars, params=params
        )

    # ---- Run replay per dataset x cost ----
    all_trades: list[dict] = []
    summary_blocks: dict[str, dict] = {}

    for ds_name, ds_signals in datasets_map.items():
        for cost_name in costs:
            trades, skips = engine.replay_dataset(
                ds_signals,
                bars_by_ticker,
                cost_model_name=cost_name,
                dataset_name=ds_name,
            )
            block = {
                "dataset": ds_name,
                "cost": cost_name,
                "n_signals": len(ds_signals),
                "n_traded": len(trades),
                "skips": skips,
                "overall": calculate_cell_metrics(trades, len(ds_signals)),
                "score_buckets": analyze_score_buckets(trades, ds_signals),
                "confidence_buckets": analyze_confidence_buckets(trades, ds_signals),
            }
            summary_blocks[f"{ds_name}__{cost_name}"] = block
            for t in trades:
                all_trades.append(t.to_dict())
            print(
                f"  [{ds_name} x {cost_name}] traded={len(trades)} "
                f"skips={sum(skips.values())} win%="
                f"{block['overall']['win_rate']:.1%} avgR={block['overall']['avg_r_net']:.3f}"
            )

    # ---- Cross-cutting analyses (raw dataset, base cost) ----
    raw_signals = datasets_map.get("raw") or signals
    extra: dict[str, Any] = {}
    if "raw" in datasets_map and "base" in costs:
        extra["indicator_filters"] = evaluate_indicator_filters(
            raw_signals, bars_by_ticker, engine, cost_model_name="base", dataset_name="raw"
        )
        extra["entry_delays"] = evaluate_entry_delays(
            raw_signals, bars_by_ticker, engine, cost_model_name="base", dataset_name="raw"
        )
        extra["hysteresis"] = evaluate_hysteresis(
            raw_signals,
            bars_by_ticker,
            engine,
            cost_model_name="base",
            max_gap_bars=args.episode_gap_bars,
            params=params,
        )

    # ---- Decision report (long score buckets only; short = hypothetical note) ----
    long_score_cells: dict[str, dict] = {}
    decision_block: dict | None = None
    for block_key, block in summary_blocks.items():
        ds_name, cost_name = block_key.split("__")
        if block.get("dataset") == "raw" and block.get("cost") == "base":
            decision_block = block
            break
    if decision_block is None:
        # Fallback: the block with the most traded signals.
        decision_block = max(
            summary_blocks.values(),
            key=lambda b: b["overall"]["n_traded"],
            default=None,
        )
    if decision_block is not None:
        for k, v in decision_block["score_buckets"].items():
            if k.startswith("long_"):
                long_score_cells[k] = v
    decision = generate_decision_report(long_score_cells, guard_threshold=args.min_n)

    # ---- Assemble summary ----
    signal_type_counts: dict[str, int] = {}
    for s in signals:
        signal_type_counts[s.signal_type] = signal_type_counts.get(s.signal_type, 0) + 1

    data_as_of = max(
        (pd.Timestamp(bars["date"].iloc[-1]) for bars in bars_by_ticker.values()),
        default=pd.Timestamp.now(),
    )

    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "datasets": datasets,
            "costs": costs,
            "timeout_bars": args.timeout_bars,
            "episode_gap_bars": args.episode_gap_bars,
            "min_score": args.min_score,
            "min_n": args.min_n,
            "period": args.period,
            "interval": args.interval,
        },
        "meta": {
            "n_signals_loaded": len(signals),
            "n_tickers": len({s.ticker for s in signals}),
            "signal_type_counts": signal_type_counts,
            "data_as_of": data_as_of.isoformat(),
            "params_fingerprint": params_fingerprint(params),
            "confidence_keys": CONFIDENCE_KEYS,
        },
        "blocks": summary_blocks,
        "cross_cutting": extra,
        "decision": decision,
    }

    # ---- Outputs ----
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Summary written: {out_path}")

    trades_path = Path(args.trades_out) if args.trades_out else out_path.with_name(out_path.stem + "_trades.csv")
    if all_trades:
        pd.DataFrame(all_trades).to_csv(trades_path, index=False, encoding="utf-8")
        print(f"Trades written  : {trades_path} ({len(all_trades)} rows)")
    else:
        print("No trades produced; trades CSV skipped.")

    # ---- Console table ----
    print()
    print(f"{'dataset':<18} {'cost':<7} {'N':>4} {'win%':>7} {'avgR':>7} {'netR':>7} {'TP':>3} {'SL':>3} {'TO':>3} {'low_n':>6}")
    print("-" * 70)
    for block_key, block in summary_blocks.items():
        ds_name, cost_name = block_key.split("__")
        o = block["overall"]
        print(
            f"{ds_name:<18} {cost_name:<7} {o['n_traded']:>4} "
            f"{o['win_rate']:>6.1%} {o['avg_r_gross']:>7.3f} {o['avg_r_net']:>7.3f} "
            f"{o['outcomes']['TP']:>3} {o['outcomes']['SL']:>3} {o['outcomes']['TIMEOUT']:>3} "
            f"{o['low_n']!s:>6}"
        )
    print("-" * 70)
    print(f"Decision: {decision['decision_status']}")
    print(f"  eligible long cells : {decision['eligible_long_cells'] or 'none'}")
    print(f"  eligible short cells: {decision['eligible_short_cells'] or 'none'} (hypothetical)")
    print(f"  top sample cells    : {[c['cell'] for c in decision['top_sample_cells']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
