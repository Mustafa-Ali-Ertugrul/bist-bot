"""Replay the signals stored in bist_signals.db over historical daily bars.

Read-only: the database is only queried through ``SignalsRepository``; the
indicator-driven backtester is untouched.

Usage (from repo root):
    python scripts/run_signal_replay.py
    python scripts/run_signal_replay.py --dataset raw --cost base
    python scripts/run_signal_replay.py --dataset all --cost all --timeout-bars 5
    python scripts/run_signal_replay.py --ticker THYAO.IS --min-score 20
    python scripts/run_signal_replay.py --out results/signal_replay_smoke.json

Outputs:
    results/signal_replay_trades.csv    (one row per replayed trade)
    results/signal_replay_summary.json  (dataset x cost x bucket breakdown,
                                         guard status, decision block)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bist_bot.backtest.signal_replay import (  # noqa: E402
    DATASET_EPISODES,
    DATASET_FIRST_ACTIONABLE,
    DATASET_HYSTERESIS,
    DATASET_RAW,
    DEFAULT_HISTORY_PERIOD,
    DEFAULT_TIMEOUT_BARS,
    MIN_SAMPLE_SIZE,
    FetcherBarProvider,
    ReplayConfig,
    build_dataset,
    build_summary,
    csv_bar_provider,
    entry_delay_analysis,
    load_stored_signals,
    replay_matrix,
    run_replay,
    summarize_trades,
    write_summary_json,
    write_trades_csv,
)
from bist_bot.strategy.params import StrategyParams  # noqa: E402

DEFAULT_SUMMARY = REPO_ROOT / "results" / "signal_replay_summary.json"
DEFAULT_TRADES = REPO_ROOT / "results" / "signal_replay_trades.csv"
DATASET_CHOICES = (DATASET_RAW, DATASET_EPISODES, DATASET_FIRST_ACTIONABLE, "all")
COST_CHOICES = ("zero", "base", "stress", "all")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stored-signal replay (Faz 2)")
    parser.add_argument("--dataset", choices=DATASET_CHOICES, default="all")
    parser.add_argument("--cost", choices=COST_CHOICES, default="all")
    parser.add_argument("--timeout-bars", type=int, default=DEFAULT_TIMEOUT_BARS)
    parser.add_argument("--min-score", type=float, default=None, help="filter on abs(score)")
    parser.add_argument("--ticker", type=str, default=None)
    parser.add_argument("--limit", type=int, default=10_000, help="max stored signals to read")
    parser.add_argument(
        "--db-path", type=str, default=None, help="explicit SQLite file (default: settings.DB_PATH)"
    )
    parser.add_argument("--period", type=str, default=DEFAULT_HISTORY_PERIOD)
    parser.add_argument("--min-n", type=int, default=MIN_SAMPLE_SIZE, help="evidence guard")
    parser.add_argument("--out", type=str, default=str(DEFAULT_SUMMARY))
    parser.add_argument("--trades-out", type=str, default=None)
    parser.add_argument(
        "--bars-dir",
        type=str,
        default=None,
        help="read bars from <dir>/<TICKER>.csv instead of the network (offline replay)",
    )
    return parser.parse_args(argv)


def _resolve_trades_path(args: argparse.Namespace) -> Path:
    if args.trades_out:
        return Path(args.trades_out)
    out_path = Path(args.out)
    if out_path.resolve() == DEFAULT_SUMMARY.resolve():
        return DEFAULT_TRADES
    return out_path.with_name(f"{out_path.stem}_trades.csv")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    datasets = (
        (DATASET_RAW, DATASET_EPISODES, DATASET_FIRST_ACTIONABLE)
        if args.dataset == "all"
        else (args.dataset,)
    )
    costs = ("zero", "base", "stress") if args.cost == "all" else (args.cost,)

    signals, rejected = load_stored_signals(
        limit=args.limit, ticker=args.ticker, db_path=args.db_path
    )
    if args.min_score is not None:
        signals = [item for item in signals if abs(item.score) >= float(args.min_score)]

    buy_threshold = float(StrategyParams.from_settings().buy_threshold)
    config = ReplayConfig(
        timeout_bars=int(args.timeout_bars),
        cost_scenario=costs[0],
        min_sample_size=int(args.min_n),
    )

    summary_path = Path(args.out)
    trades_path = _resolve_trades_path(args)

    if not signals:
        payload = build_summary(
            signals=[],
            rejected=rejected,
            runs={},
            dataset_signals={},
            config=config,
            buy_threshold=buy_threshold,
            extra={"status": "no_stored_signals"},
        )
        write_summary_json(payload, summary_path)
        write_trades_csv([], trades_path)
        print("WARNING: no stored signals found (empty or missing bist_signals.db).")
        print(f"  summary: {summary_path}")
        print(f"  trades : {trades_path}")
        return 0

    provider = (
        csv_bar_provider(args.bars_dir) if args.bars_dir else FetcherBarProvider(period=args.period)
    )
    runs, dataset_signals = replay_matrix(
        signals,
        provider,
        datasets=datasets,
        cost_scenarios=costs,
        config=config,
        buy_threshold=buy_threshold,
    )

    primary_dataset = datasets[0]
    primary_signals = dataset_signals[primary_dataset]
    variants = {
        "entry_delay": entry_delay_analysis(
            primary_signals,
            provider,
            config=replace(config, cost_scenario=costs[0]),
            dataset=primary_dataset,
        ),
        "hysteresis": _hysteresis_block(signals, provider, config, buy_threshold, costs[0]),
        "primary_dataset": primary_dataset,
        "primary_cost": costs[0],
    }

    payload = build_summary(
        signals=signals,
        rejected=rejected,
        runs=runs,
        dataset_signals=dataset_signals,
        config=config,
        buy_threshold=buy_threshold,
        extra={"status": "ok", "variants": variants},
    )
    write_summary_json(payload, summary_path)

    all_trades = [
        trade for per_cost in runs.values() for run in per_cost.values() for trade in run.trades
    ]
    write_trades_csv(all_trades, trades_path)

    _print_console_report(payload, runs, summary_path, trades_path)
    return 0


def _hysteresis_block(signals, provider, config, buy_threshold, cost_scenario) -> dict:
    hysteresis_signals = build_dataset(signals, DATASET_HYSTERESIS, buy_threshold=buy_threshold)
    run = run_replay(
        hysteresis_signals,
        provider,
        config=replace(config, cost_scenario=cost_scenario),
        dataset=DATASET_HYSTERESIS,
    )
    return {
        "rule": "enter on the 2nd consecutive same-type signal of an episode",
        "signal_count": len(hysteresis_signals),
        "summary": summarize_trades(run.trades, min_sample_size=config.min_sample_size),
        "skipped": len(run.skipped),
    }


def _print_console_report(payload, runs, summary_path: Path, trades_path: Path) -> None:
    inventory = payload["signal_inventory"]
    print("=" * 72)
    print("STORED SIGNAL REPLAY")
    print("=" * 72)
    print(
        f"  signals: {inventory['valid_signals']} valid / "
        f"{inventory['rejected_signals']} rejected  "
        f"({inventory['distinct_tickers']} tickers)"
    )
    print(f"  by type: {inventory['by_signal_type']}")
    print(f"  guard  : N >= {payload['config']['min_sample_size']}")
    print("-" * 72)
    header = (
        f"{'dataset':<18}{'cost':<9}{'N':>4}{'win%':>8}{'avgR':>9}"
        f"{'netR':>9}{'TP/SL/TO':>12}{'low_n':>8}"
    )
    print(header)
    for dataset, per_cost in runs.items():
        for scenario in per_cost:
            block = payload["datasets"][dataset]["costs"][scenario]["overall"]
            outcomes = block["outcomes"]
            mix = f"{outcomes['TP']}/{outcomes['SL']}/{outcomes['TIMEOUT']}"
            print(
                f"{dataset:<18}{scenario:<9}{block['n']:>4}{block['win_rate_pct']:>8.1f}"
                f"{block['avg_r']:>9.3f}{block['avg_net_r']:>9.3f}{mix:>12}"
                f"{block['low_n']!s:>8}"
            )
    print("-" * 72)
    print(f"  decision: {payload['decision']['note']}")
    print(f"  summary : {summary_path}")
    print(f"  trades  : {trades_path}")


if __name__ == "__main__":
    raise SystemExit(main())
