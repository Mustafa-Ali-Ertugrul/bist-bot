"""CLI for training and persisting the signal meta-model."""

from __future__ import annotations

import argparse
from pathlib import Path

from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.ml.training import (
    LabelDefinition,
    SplitConfig,
    train_meta_model_from_price_data,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the BIST Bot signal meta-model")
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=list(settings.WATCHLIST),
        help="Tickers to train on",
    )
    parser.add_argument("--period", default="2y", help="Historical period to fetch")
    parser.add_argument(
        "--output-dir",
        default=str(Path(settings.ML_MODEL_PATH) / "latest"),
        help="Artifact output directory",
    )
    parser.add_argument(
        "--horizon-bars", type=int, default=5, help="Forward label horizon in bars"
    )
    parser.add_argument(
        "--return-threshold", type=float, default=0.02, help="Positive label threshold"
    )
    parser.add_argument(
        "--train-fraction", type=float, default=0.6, help="Train split fraction"
    )
    parser.add_argument(
        "--validation-fraction",
        type=float,
        default=0.15,
        help="Validation split fraction",
    )
    parser.add_argument(
        "--calibration-fraction",
        type=float,
        default=0.1,
        help="Calibration split fraction",
    )
    parser.add_argument(
        "--calibration-method", choices=["none", "platt", "isotonic"], default="platt"
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    fetcher = BISTDataFetcher()
    price_data = {
        ticker: fetcher.fetch_single(ticker, period=args.period)
        for ticker in args.tickers
    }
    _, manifest, metrics = train_meta_model_from_price_data(
        price_data,
        output_dir=args.output_dir,
        label_definition=LabelDefinition(
            horizon_bars=args.horizon_bars,
            return_threshold=args.return_threshold,
        ),
        split_config=SplitConfig(
            train_fraction=args.train_fraction,
            validation_fraction=args.validation_fraction,
            calibration_fraction=args.calibration_fraction,
        ),
        calibration_method=args.calibration_method,
    )
    print(f"Artifacts saved to {args.output_dir}")
    print(
        f"Train {manifest['train_range']['start']} -> {manifest['train_range']['end']} | "
        f"Test {manifest['test_range']['start']} -> {manifest['test_range']['end']}"
    )
    print(
        f"Validation Brier {metrics['validation']['brier_score']:.4f} | "
        f"Test Brier {metrics['test']['brier_score']:.4f}"
    )


if __name__ == "__main__":
    main()
