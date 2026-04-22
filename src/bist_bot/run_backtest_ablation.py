"""CLI for running backtest ablations with a persisted meta-model artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bist_bot.backtest import Backtester
from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.ml.training import load_training_artifacts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run backtest ablations with a saved meta-model"
    )
    parser.add_argument(
        "--artifact", required=True, help="Artifact directory containing model files"
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=list(settings.WATCHLIST),
        help="Tickers to backtest",
    )
    parser.add_argument("--period", default="1y", help="Historical period to fetch")
    parser.add_argument(
        "--output-dir", default="data", help="Directory for ablation JSON exports"
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    model, _, _ = load_training_artifacts(args.artifact)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fetcher = BISTDataFetcher()

    for ticker in args.tickers:
        df = fetcher.fetch_single(ticker, period=args.period)
        if df is None or df.empty:
            continue
        ablation = Backtester(
            initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0),
            meta_model=model,
            min_probability=float(getattr(settings, "MIN_SIGNAL_PROBABILITY", 0.5)),
            fractional_kelly=float(getattr(settings, "KELLY_FRACTION_SCALE", 0.25)),
            max_position_cap_pct=float(getattr(settings, "MAX_POSITION_CAP_PCT", 90.0)),
        ).run_ablation(ticker, df, verbose=False)
        output_path = output_dir / f"ablation_{ticker.replace('.', '_')}.json"
        output_path.write_text(
            json.dumps(ablation.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        base = ablation.runs.get("base_fixed_size")
        meta_filter = ablation.runs.get("meta_filter_fixed_size")
        meta_kelly = ablation.runs.get("meta_filter_fractional_kelly")
        print(f"{ticker}")
        if base is not None:
            print(
                f"  base_fixed_size            trades={base.total_trades} cagr={base.cagr:.2f} sharpe={base.sharpe_ratio:.2f} mdd={base.max_drawdown_pct:.2f}"
            )
        if meta_filter is not None:
            print(
                f"  meta_filter_fixed_size     trades={meta_filter.total_trades} cagr={meta_filter.cagr:.2f} sharpe={meta_filter.sharpe_ratio:.2f} mdd={meta_filter.max_drawdown_pct:.2f}"
            )
        if meta_kelly is not None:
            print(
                f"  meta_filter_fractional_kelly trades={meta_kelly.total_trades} cagr={meta_kelly.cagr:.2f} sharpe={meta_kelly.sharpe_ratio:.2f} mdd={meta_kelly.max_drawdown_pct:.2f}"
            )
        print(f"  json={output_path}")


if __name__ == "__main__":
    main()
