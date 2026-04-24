"""CLI helpers for standard and walk-forward backtests."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import bist_bot.config as config

from bist_bot.app_logging import get_logger
from bist_bot.backtest import (
    BacktestResult,
    Backtester,
    WalkForwardResult,
    WalkForwardValidator,
)
from bist_bot.data.universe import get_universe_for_date

logger = get_logger(__name__, component="backtest_runner")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BIST Bot backtests")
    parser.add_argument(
        "--walk-forward", action="store_true", help="Run walk-forward validation"
    )
    parser.add_argument(
        "--historical-universe-date",
        type=str,
        default=None,
        help="Resolve a point-in-time universe snapshot for YYYY-MM-DD",
    )
    parser.add_argument(
        "--train-window", type=int, default=12, help="Train window in months"
    )
    parser.add_argument(
        "--test-window", type=int, default=3, help="Test window in months"
    )
    parser.add_argument("--step", type=int, default=3, help="Step size in months")
    parser.add_argument(
        "--mode",
        choices=["rolling", "anchored"],
        default="rolling",
        help="Walk-forward mode",
    )
    return parser


def run_backtest(fetcher, walk_forward: bool | None = None) -> None:
    args = _build_parser().parse_known_args(sys.argv[1:])[0]
    use_walk_forward = args.walk_forward if walk_forward is None else walk_forward

    logger.warning("backtest_survivorship_bias_warning")
    logger.info("backtest_runner_started", walk_forward=use_walk_forward)

    output_dir = Path("data")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    universe_as_of = args.historical_universe_date
    universe = (
        get_universe_for_date(
            universe_as_of, current_universe=list(config.settings.WATCHLIST)
        )
        if universe_as_of
        else list(config.settings.WATCHLIST)
    )
    if universe_as_of:
        logger.info(
            "backtest_point_in_time_universe_enabled",
            universe_as_of=universe_as_of,
            ticker_count=len(universe),
        )

    if use_walk_forward:
        walk_forward_results: list[WalkForwardResult] = []
        for ticker in universe:
            df = fetcher.fetch_single(ticker, period="2y")
            if df is None:
                continue

            validator = WalkForwardValidator(
                train_window=args.train_window,
                test_window=args.test_window,
                step=args.step,
                mode=args.mode,
            )
            output_path = (
                output_dir / f"walkforward_{ticker.replace('.', '_')}_{timestamp}.json"
            )
            walk_forward_result = validator.run(
                ticker,
                df,
                initial_capital=getattr(config.settings, "INITIAL_CAPITAL", 8500.0),
                output_path=output_path,
                universe_as_of=universe_as_of,
            )
            if walk_forward_result is not None:
                walk_forward_results.append(walk_forward_result)
                print(
                    f"{ticker}: OOS %{walk_forward_result.combined_metrics['total_return_pct']:+.2f} | "
                    f"Sharpe {walk_forward_result.combined_metrics['sharpe']:.2f} | "
                    f"Windows {len(walk_forward_result.windows)}"
                )

        if not walk_forward_results:
            return

        avg_return = sum(
            r.combined_metrics["total_return_pct"] for r in walk_forward_results
        ) / len(walk_forward_results)
        avg_sharpe = sum(
            r.combined_metrics["sharpe"] for r in walk_forward_results
        ) / len(walk_forward_results)
        total_windows = sum(len(r.windows) for r in walk_forward_results)
        print(f"\n{'═' * 55}")
        print("📊 GENEL WALK-FORWARD ÖZETİ")
        print(f"{'═' * 55}")
        print(f"  Test edilen : {len(walk_forward_results)} hisse")
        print(f"  Toplam pencere: {total_windows}")
        print(f"  Ort. OOS getiri : %{avg_return:.2f}")
        print(f"  Ort. Sharpe     : {avg_sharpe:.2f}")
        print(f"{'═' * 55}")
        return

    backtest_results: list[BacktestResult] = []
    for ticker in universe:
        df = fetcher.fetch_single(ticker, period="1y")
        if df is None:
            continue

        backtester = Backtester(
            initial_capital=getattr(config.settings, "INITIAL_CAPITAL", 8500.0)
        )
        output_path = output_dir / f"backtest_{ticker.replace('.', '_')}.json"
        backtest_result = backtester.run(
            ticker,
            df,
            verbose=False,
            output_path=output_path,
            universe_as_of=universe_as_of,
        )
        if backtest_result is not None:
            backtest_results.append(backtest_result)
            print(backtest_result)

    if not backtest_results:
        return

    avg_return = sum(r.total_return_pct for r in backtest_results) / len(
        backtest_results
    )
    avg_winrate = sum(r.win_rate for r in backtest_results) / len(backtest_results)
    total_trades = sum(r.total_trades for r in backtest_results)

    print(f"\n{'═' * 55}")
    print("📊 GENEL BACKTEST ÖZETİ")
    print(f"{'═' * 55}")
    print(f"  Test edilen : {len(backtest_results)} hisse")
    print(f"  Toplam işlem: {total_trades}")
    print(f"  Ort. getiri : %{avg_return:.2f}")
    print(f"  Ort. win rate: %{avg_winrate:.1f}")

    best = max(backtest_results, key=lambda result: result.total_return_pct)
    worst = min(backtest_results, key=lambda result: result.total_return_pct)
    print(f"  En iyi      : {best.ticker} (%{best.total_return_pct:+.2f})")
    print(f"  En kötü     : {worst.ticker} (%{worst.total_return_pct:+.2f})")
    print(f"{'═' * 55}")


def main() -> None:
    from bist_bot.data.fetcher import BISTDataFetcher

    run_backtest(BISTDataFetcher())


if __name__ == "__main__":
    main()
