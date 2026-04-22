"""Probability meta-model and calibration helpers."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, cast

import numpy as np
import pandas as pd

from sklearn.isotonic import IsotonicRegression  # type: ignore[import-not-found]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]


CalibrationMethod = Literal["none", "platt", "isotonic"]


class ProbabilityCalibrator:
    def __init__(self, method: CalibrationMethod = "platt") -> None:
        self.method = method
        self._model: LogisticRegression | IsotonicRegression | None = None

    def fit(
        self, raw_probabilities: Iterable[float], labels: Iterable[int]
    ) -> "ProbabilityCalibrator":
        probabilities = np.clip(
            np.asarray(list(raw_probabilities), dtype=float), 1e-6, 1.0 - 1e-6
        )
        targets = np.asarray(list(labels), dtype=int)
        if probabilities.size == 0 or probabilities.size != targets.size:
            raise ValueError("Calibration data must be non-empty and aligned")
        if self.method == "none":
            self._model = None
            return self
        if self.method == "platt":
            model = LogisticRegression()
            model.fit(probabilities.reshape(-1, 1), targets)
            self._model = model
            return self
        model = IsotonicRegression(out_of_bounds="clip")
        model.fit(probabilities, targets)
        self._model = model
        return self

    def predict(self, raw_probabilities: Iterable[float]) -> np.ndarray:
        probabilities = np.clip(
            np.asarray(list(raw_probabilities), dtype=float), 1e-6, 1.0 - 1e-6
        )
        if self._model is None:
            return probabilities
        if self.method == "platt":
            model = cast(LogisticRegression, self._model)
            return model.predict_proba(probabilities.reshape(-1, 1))[:, 1]
        return np.clip(
            np.asarray(
                cast(IsotonicRegression, self._model).predict(probabilities),
                dtype=float,
            ),
            0.0,
            1.0,
        )


@dataclass
class SignalMetaModel:
    calibration_method: CalibrationMethod = "platt"
    calibration_holdout_fraction: float = 0.2

    def __post_init__(self) -> None:
        self.model = LogisticRegression(max_iter=1000)
        self.calibrator = ProbabilityCalibrator(self.calibration_method)
        self.feature_names: list[str] = []

    def fit(self, features: pd.DataFrame, labels: Iterable[int]) -> "SignalMetaModel":
        if features.empty:
            raise ValueError("features must not be empty")
        targets = np.asarray(list(labels), dtype=int)
        if len(features) != len(targets):
            raise ValueError("features and labels must have the same length")
        self.feature_names = list(features.columns)
        holdout_size = int(len(features) * self.calibration_holdout_fraction)
        if self.calibration_method == "none" or holdout_size < 5:
            self.model.fit(features, targets)
            self.calibrator = ProbabilityCalibrator("none")
            return self

        split_index = len(features) - holdout_size
        train_x = features.iloc[:split_index]
        train_y = targets[:split_index]
        calib_x = features.iloc[split_index:]
        calib_y = targets[split_index:]
        self.model.fit(train_x, train_y)
        raw_probabilities = self.model.predict_proba(calib_x)[:, 1]
        self.calibrator.fit(raw_probabilities, calib_y)
        return self

    def predict_probability(
        self, features: Mapping[str, float] | pd.DataFrame
    ) -> float:
        frame = self._coerce_features(features)
        raw_probability = self.model.predict_proba(frame)[:, 1]
        return float(self.calibrator.predict(raw_probability)[0])

    def _coerce_features(
        self, features: Mapping[str, float] | pd.DataFrame
    ) -> pd.DataFrame:
        if isinstance(features, pd.DataFrame):
            frame = features.copy()
        else:
            frame = pd.DataFrame([dict(features)])
        if not self.feature_names:
            self.feature_names = list(frame.columns)
        missing = [name for name in self.feature_names if name not in frame.columns]
        if missing:
            raise ValueError(f"Missing meta-model feature(s): {', '.join(missing)}")
        return cast(pd.DataFrame, frame[self.feature_names].astype(float))

    def save_artifacts(
        self,
        output_dir: str | Path,
        *,
        manifest: Mapping[str, object],
        metrics: Mapping[str, object],
    ) -> Path:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "meta_model.pkl").write_bytes(pickle.dumps(self.model))
        (path / "probability_calibrator.pkl").write_bytes(pickle.dumps(self.calibrator))
        (path / "feature_columns.json").write_text(
            json.dumps(self.feature_names, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (path / "training_manifest.json").write_text(
            json.dumps(dict(manifest), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        (path / "metrics.json").write_text(
            json.dumps(dict(metrics), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load_artifacts(cls, artifact_dir: str | Path) -> "SignalMetaModel":
        path = Path(artifact_dir)
        feature_names = json.loads(
            (path / "feature_columns.json").read_text(encoding="utf-8")
        )
        model = pickle.loads((path / "meta_model.pkl").read_bytes())
        calibrator = pickle.loads((path / "probability_calibrator.pkl").read_bytes())
        instance = cls(getattr(calibrator, "method", "platt"))
        instance.model = model
        instance.calibrator = calibrator
        instance.feature_names = list(feature_names)
        return instance
