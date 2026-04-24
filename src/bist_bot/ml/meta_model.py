"""Probability meta-model and calibration helpers."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, cast

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-not-found]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
from sklearn.model_selection import TimeSeriesSplit  # type: ignore[import-not-found]

try:  # pragma: no cover - optional heavy dependency
    from xgboost import XGBClassifier  # type: ignore[import-not-found]

    _HAS_XGBOOST = True
except ImportError:  # pragma: no cover
    _HAS_XGBOOST = False


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

    def predict(self, raw_probabilities: Iterable[float]) -> npt.NDArray[np.float64]:
        probabilities = np.clip(
            np.asarray(list(raw_probabilities), dtype=float), 1e-6, 1.0 - 1e-6
        )
        if self._model is None:
            return cast(npt.NDArray[np.float64], probabilities)
        if self.method == "platt":
            model = cast(LogisticRegression, self._model)
            calibrated = model.predict_proba(probabilities.reshape(-1, 1))[:, 1]
            return cast(npt.NDArray[np.float64], calibrated)
        return cast(
            npt.NDArray[np.float64],
            np.clip(
                np.asarray(
                    cast(IsotonicRegression, self._model).predict(probabilities),
                    dtype=float,
                ),
                0.0,
                1.0,
            ),
        )


# ---------------------------------------------------------------------------
# Default XGBoost hyper-parameters tuned for financial signal classification.
# Shallow trees + aggressive sub-sampling fight the low signal-to-noise ratio
# that is typical of BIST technical-indicator features.
# ---------------------------------------------------------------------------
_DEFAULT_XGB_PARAMS: dict[str, Any] = {
    "n_estimators": 150,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "random_state": 42,
    "verbosity": 0,
}


def _build_classifier(xgb_params: dict[str, Any] | None = None) -> Any:
    """Create the underlying classifier, preferring XGBoost when available."""
    if _HAS_XGBOOST:
        params = {**_DEFAULT_XGB_PARAMS, **(xgb_params or {})}
        return XGBClassifier(**params)
    # Graceful fallback: keep the project functional without XGBoost
    return LogisticRegression(max_iter=1000)  # pragma: no cover


@dataclass
class SignalMetaModel:
    calibration_method: CalibrationMethod = "platt"
    n_cv_splits: int = 5
    xgb_params: dict[str, Any] = field(default_factory=dict)

    # Backward-compatible alias so old tests using the positional param still work
    calibration_holdout_fraction: float = 0.2

    def __post_init__(self) -> None:
        self.model = _build_classifier(self.xgb_params or None)
        self.calibrator = ProbabilityCalibrator(self.calibration_method)
        self.feature_names: list[str] = []

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, features: pd.DataFrame, labels: Iterable[int]) -> "SignalMetaModel":
        """Train the model and calibrate probabilities with Time-Series CV.

        Walk-forward out-of-fold predictions are used to fit the calibrator
        so that calibrated probabilities are entirely free of look-ahead bias.
        The final model is then retrained on the *full* dataset for live use.
        """
        if features.empty:
            raise ValueError("features must not be empty")

        targets = np.asarray(list(labels), dtype=int)
        if len(features) != len(targets):
            raise ValueError("features and labels must have the same length")
        self.feature_names = list(features.columns)

        # ------ Simple path: no calibration ------
        if self.calibration_method == "none":
            self.model.fit(features, targets)
            self.calibrator = ProbabilityCalibrator("none")
            return self

        # ------ Time-Series CV path ------
        effective_splits = min(self.n_cv_splits, len(features) - 1)
        if effective_splits < 2:
            # Not enough data for meaningful CV – train directly
            self.model.fit(features, targets)
            raw_probs = self.model.predict_proba(features)[:, 1]
            self.calibrator.fit(raw_probs, targets)
            return self

        tscv = TimeSeriesSplit(n_splits=effective_splits)
        oof_predictions = np.full(len(features), np.nan)

        for train_idx, test_idx in tscv.split(features):
            x_train = features.iloc[train_idx]
            y_train = targets[train_idx]
            x_test = features.iloc[test_idx]

            fold_model = _build_classifier(self.xgb_params or None)
            fold_model.fit(x_train, y_train)
            oof_predictions[test_idx] = fold_model.predict_proba(x_test)[:, 1]

        # Gather only the indices that received OOF predictions
        valid_mask = ~np.isnan(oof_predictions)
        calib_probs = oof_predictions[valid_mask]
        calib_targets = targets[valid_mask]

        if len(calib_probs) >= 5:
            self.calibrator.fit(calib_probs, calib_targets)
        else:
            self.calibrator = ProbabilityCalibrator("none")  # pragma: no cover

        # Retrain on full dataset for production inference
        self.model = _build_classifier(self.xgb_params or None)
        self.model.fit(features, targets)
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

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
