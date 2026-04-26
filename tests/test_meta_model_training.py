from __future__ import annotations

from datetime import datetime

import pandas as pd

from bist_bot.ml.features import FEATURE_COLUMNS
from bist_bot.ml.training import (
    LabelDefinition,
    SplitConfig,
    load_training_artifacts,
    split_dataset,
    train_meta_model_from_dataset,
)


def build_dataset(rows: int = 80) -> pd.DataFrame:
    data = []
    dates = pd.date_range(datetime(2024, 1, 1), periods=rows, freq="D")
    for idx, date in enumerate(dates):
        score = 10 + idx
        label = 1 if idx % 5 in {2, 3, 4} else 0
        data.append(
            {
                "ticker": "TEST.IS",
                "date": date,
                "future_return": 0.03 if label else -0.01,
                "label": label,
                "score": float(score),
                "adx": 20.0 + label * 10,
                "rsi": 45.0 + label * 12,
                "volume_ratio": 1.0 + label * 0.4,
                "atr_pct": 0.02,
                "risk_reward_ratio": 2.0,
                "volatility_scale": 1.0,
                "correlation_scale": 1.0,
                "trend_bias": 1.0,
                "close_vs_ema_long": 0.01 + label * 0.02,
            }
        )
    return pd.DataFrame(data)


def test_split_dataset_creates_time_ordered_partitions() -> None:
    dataset = build_dataset()

    splits = split_dataset(
        dataset,
        SplitConfig(train_fraction=0.5, validation_fraction=0.2, calibration_fraction=0.1),
    )

    assert splits["train"]["date"].max() < splits["validation"]["date"].min()
    assert splits["validation"]["date"].max() < splits["calibration"]["date"].min()
    assert splits["calibration"]["date"].max() < splits["test"]["date"].min()


def test_train_meta_model_persists_expected_artifacts(tmp_path) -> None:
    dataset = build_dataset()

    model, manifest, metrics = train_meta_model_from_dataset(
        dataset,
        split_config=SplitConfig(
            train_fraction=0.5, validation_fraction=0.2, calibration_fraction=0.1
        ),
        label_definition=LabelDefinition(horizon_bars=5, return_threshold=0.02),
        calibration_method="platt",
        output_dir=tmp_path,
    )

    assert model.feature_names == FEATURE_COLUMNS
    assert (tmp_path / "meta_model.pkl").exists()
    assert (tmp_path / "probability_calibrator.pkl").exists()
    assert (tmp_path / "feature_columns.json").exists()
    assert (tmp_path / "training_manifest.json").exists()
    assert (tmp_path / "metrics.json").exists()
    assert manifest["label_definition"]["horizon_bars"] == 5
    assert "test" in metrics
    assert metrics["test"]["brier_score"] >= 0.0

    loaded_model, loaded_manifest, loaded_metrics = load_training_artifacts(tmp_path)
    probability = loaded_model.predict_probability(dataset.iloc[[0]][FEATURE_COLUMNS])

    assert 0.0 <= probability <= 1.0
    assert loaded_manifest["feature_list"] == FEATURE_COLUMNS
    assert loaded_metrics["validation"]["count"] > 0
