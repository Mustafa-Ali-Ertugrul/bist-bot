"""Time-aware training pipeline for the signal meta-model."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.ml.features import FEATURE_COLUMNS, build_feature_payload, to_float
from bist_bot.ml.meta_model import (
    CalibrationMethod,
    ProbabilityCalibrator,
    SignalMetaModel,
)

try:  # pragma: no cover - optional dependency behavior
    from sklearn.metrics import log_loss, roc_auc_score  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    log_loss = None
    roc_auc_score = None


@dataclass(frozen=True)
class LabelDefinition:
    horizon_bars: int = 5
    return_threshold: float = 0.02


@dataclass(frozen=True)
class SplitConfig:
    train_fraction: float = 0.6
    validation_fraction: float = 0.15
    calibration_fraction: float = 0.1


def _score_row(row: pd.Series) -> float:
    score = 0.0
    rsi = to_float(row.get("rsi"), 50.0)
    if rsi < settings.RSI_OVERSOLD:
        score += 20.0
    elif rsi > settings.RSI_OVERBOUGHT:
        score -= 20.0

    sma_cross = str(row.get("sma_cross", "NONE"))
    if sma_cross == "GOLDEN_CROSS":
        score += 20.0
    elif sma_cross == "DEATH_CROSS":
        score -= 20.0

    sma_fast = to_float(row.get(f"sma_{settings.SMA_FAST}"))
    sma_slow = to_float(row.get(f"sma_{settings.SMA_SLOW}"))
    if sma_fast > 0 and sma_slow > 0:
        score += 5.0 if sma_fast > sma_slow else -5.0

    macd_cross = str(row.get("macd_cross", "NONE"))
    if macd_cross == "BULLISH":
        score += 15.0
    elif macd_cross == "BEARISH":
        score -= 15.0

    bb_position = str(row.get("bb_position", "MIDDLE"))
    if bb_position == "BELOW_LOWER":
        score += 10.0
    elif bb_position == "ABOVE_UPPER":
        score -= 10.0
    return float(max(-100.0, min(100.0, score)))


def build_training_dataset(
    price_data: dict[str, pd.DataFrame],
    *,
    label_definition: LabelDefinition,
    target_rr: float = 2.0,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ticker, raw_df in price_data.items():
        if raw_df is None or raw_df.empty:
            continue
        enriched = TechnicalIndicators.add_all(raw_df.copy())
        enriched = enriched.sort_index()
        future_close = enriched["close"].shift(-label_definition.horizon_bars)
        future_return = (future_close / enriched["close"]) - 1.0
        for idx in range(len(enriched) - label_definition.horizon_bars):
            row = enriched.iloc[idx]
            close_price = to_float(row.get("close"))
            if close_price <= 0:
                continue
            score = _score_row(row)
            stop_loss = to_float(row.get("stop_loss_atr"), close_price * 0.95)
            risk_per_share = max(close_price - stop_loss, close_price * 0.01)
            target_price = max(close_price + risk_per_share * target_rr, close_price)
            feature_row: dict[str, Any] = dict(
                build_feature_payload(
                    row,
                    score=score,
                    stop_loss=stop_loss,
                    target_price=target_price,
                )
            )
            feature_row["ticker"] = ticker
            feature_row["date"] = str(enriched.index[idx])[:10]
            feature_row["future_return"] = float(future_return.iloc[idx])
            feature_row["label"] = int(future_return.iloc[idx] >= label_definition.return_threshold)
            rows.append(feature_row)
    dataset = pd.DataFrame(rows)
    if dataset.empty:
        raise ValueError("No training rows could be built from price data")
    dataset = dataset.dropna(subset=[*FEATURE_COLUMNS, "future_return", "label"])
    dataset = dataset.sort_values(["date", "ticker"]).reset_index(drop=True)
    return dataset


def _date_range(frame: pd.DataFrame) -> dict[str, str | None]:
    if frame.empty:
        return {"start": None, "end": None}
    date_series = pd.to_datetime(frame["date"])
    return {
        "start": pd.Timestamp(date_series.min()).strftime("%Y-%m-%d"),
        "end": pd.Timestamp(date_series.max()).strftime("%Y-%m-%d"),
    }


def split_dataset(dataset: pd.DataFrame, split_config: SplitConfig) -> dict[str, pd.DataFrame]:
    unique_dates = sorted(pd.to_datetime(dataset["date"].drop_duplicates()).tolist())
    if len(unique_dates) < 10:
        raise ValueError("Need at least 10 unique dates for time-based split")
    train_end = max(1, int(len(unique_dates) * split_config.train_fraction))
    validation_end = train_end + max(1, int(len(unique_dates) * split_config.validation_fraction))
    calibration_end = validation_end + max(
        1, int(len(unique_dates) * split_config.calibration_fraction)
    )
    train_dates = list(unique_dates[:train_end])
    validation_dates = list(unique_dates[train_end:validation_end])
    calibration_dates = list(unique_dates[validation_end:calibration_end])
    test_dates = list(unique_dates[calibration_end:])
    date_series = pd.to_datetime(dataset["date"])
    if not validation_dates or not calibration_dates or not test_dates:
        raise ValueError("Split config leaves an empty validation/calibration/test partition")
    return {
        "train": dataset[date_series.isin(train_dates)].reset_index(drop=True),
        "validation": dataset[date_series.isin(validation_dates)].reset_index(drop=True),
        "calibration": dataset[date_series.isin(calibration_dates)].reset_index(drop=True),
        "test": dataset[date_series.isin(test_dates)].reset_index(drop=True),
    }


def _classification_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    probabilities = np.clip(probabilities.astype(float), 1e-6, 1.0 - 1e-6)
    metrics: dict[str, Any] = {
        "count": len(labels),
        "positive_rate": round(float(np.mean(labels)), 4) if len(labels) else 0.0,
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 4)
        if len(labels)
        else 0.0,
    }
    if len(labels) and log_loss is not None:
        metrics["log_loss"] = round(float(log_loss(labels, probabilities, labels=[0, 1])), 4)
    if len(np.unique(labels)) > 1 and roc_auc_score is not None:
        metrics["roc_auc"] = round(float(roc_auc_score(labels, probabilities)), 4)
    bucket_rows = []
    for low, high in [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)]:
        mask = (probabilities >= low) & (probabilities < high)
        bucket_rows.append(
            {
                "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
                "count": int(np.sum(mask)),
                "avg_probability": round(float(np.mean(probabilities[mask])), 4)
                if np.any(mask)
                else 0.0,
                "realized_rate": round(float(np.mean(labels[mask])), 4) if np.any(mask) else 0.0,
            }
        )
    metrics["probability_buckets"] = bucket_rows
    return metrics


def _git_commit() -> str:
    root = Path(__file__).resolve().parents[3]
    try:
        output = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True)
        return output.strip()
    except Exception:
        return "unknown"


def train_meta_model_from_dataset(
    dataset: pd.DataFrame,
    *,
    split_config: SplitConfig,
    label_definition: LabelDefinition,
    calibration_method: CalibrationMethod,
    output_dir: str | Path,
) -> tuple[SignalMetaModel, dict[str, Any], dict[str, Any]]:
    splits = split_dataset(dataset, split_config)
    model = SignalMetaModel(calibration_method="none")
    train_features = pd.DataFrame(splits["train"][FEATURE_COLUMNS])
    train_labels = splits["train"]["label"].to_numpy(dtype=int)
    model.fit(train_features, train_labels)

    validation_probs = model.model.predict_proba(splits["validation"][FEATURE_COLUMNS])[:, 1]
    calibration_probs = model.model.predict_proba(splits["calibration"][FEATURE_COLUMNS])[:, 1]
    train_probs = model.model.predict_proba(train_features)[:, 1]
    test_probs = model.model.predict_proba(splits["test"][FEATURE_COLUMNS])[:, 1]
    calibrator = ProbabilityCalibrator(calibration_method)
    calibrator.fit(calibration_probs, splits["calibration"]["label"].to_numpy(dtype=int))
    model.calibrator = calibrator
    model.feature_names = list(FEATURE_COLUMNS)

    metrics = {
        "train": _classification_metrics(
            train_labels,
            model.calibrator.predict(train_probs),
        ),
        "validation": _classification_metrics(
            splits["validation"]["label"].to_numpy(dtype=int),
            model.calibrator.predict(validation_probs),
        ),
        "calibration": _classification_metrics(
            splits["calibration"]["label"].to_numpy(dtype=int),
            model.calibrator.predict(calibration_probs),
        ),
        "test": _classification_metrics(
            splits["test"]["label"].to_numpy(dtype=int),
            model.calibrator.predict(test_probs),
        ),
    }
    manifest = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "train_range": _date_range(splits["train"]),
        "validation_range": _date_range(splits["validation"]),
        "calibration_range": _date_range(splits["calibration"]),
        "test_range": _date_range(splits["test"]),
        "label_definition": {
            "horizon_bars": label_definition.horizon_bars,
            "return_threshold": label_definition.return_threshold,
        },
        "horizon": label_definition.horizon_bars,
        "threshold": label_definition.return_threshold,
        "calibration_method": calibration_method,
        "feature_list": list(FEATURE_COLUMNS),
        "feature_schema_path": "feature_columns.json",
        "commit": _git_commit(),
        "version": 1,
        "row_counts": {name: len(frame) for name, frame in splits.items()},
    }
    model.save_artifacts(output_dir, manifest=manifest, metrics=metrics)
    return model, manifest, metrics


def train_meta_model_from_price_data(
    price_data: dict[str, pd.DataFrame],
    *,
    output_dir: str | Path,
    label_definition: LabelDefinition,
    split_config: SplitConfig,
    calibration_method: CalibrationMethod = "platt",
) -> tuple[SignalMetaModel, dict[str, Any], dict[str, Any]]:
    dataset = build_training_dataset(price_data, label_definition=label_definition)
    return train_meta_model_from_dataset(
        dataset,
        split_config=split_config,
        label_definition=label_definition,
        calibration_method=calibration_method,
        output_dir=output_dir,
    )


def load_training_artifacts(
    artifact_dir: str | Path,
) -> tuple[SignalMetaModel, dict[str, Any], dict[str, Any]]:
    path = Path(artifact_dir)
    model = SignalMetaModel.load_artifacts(path)
    manifest = json.loads((path / "training_manifest.json").read_text(encoding="utf-8"))
    metrics = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    return model, manifest, metrics
