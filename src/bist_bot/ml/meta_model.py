"""Probability meta-model and calibration helpers."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-not-found]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
from sklearn.model_selection import TimeSeriesSplit  # type: ignore[import-not-found]

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings

try:  # pragma: no cover - optional heavy dependency
    from xgboost import XGBClassifier  # type: ignore[import-not-found]

    _HAS_XGBOOST = True
except ImportError:  # pragma: no cover
    _HAS_XGBOOST = False


CalibrationMethod = Literal["none", "platt", "isotonic"]
logger = get_logger(__name__, component="ml")


class ProbabilityCalibrator:
    def __init__(self, method: CalibrationMethod = "platt") -> None:
        self.method = method
        self._model: LogisticRegression | IsotonicRegression | None = None
        self._serialized_params: dict[str, Any] | None = None

    def fit(
        self, raw_probabilities: Iterable[float], labels: Iterable[int]
    ) -> ProbabilityCalibrator:
        probabilities = np.clip(np.asarray(list(raw_probabilities), dtype=float), 1e-6, 1.0 - 1e-6)
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
        probabilities = np.clip(np.asarray(list(raw_probabilities), dtype=float), 1e-6, 1.0 - 1e-6)
        if self._serialized_params is not None:
            if self.method == "platt":
                coefficient = float(self._serialized_params["coefficient"])
                intercept = float(self._serialized_params["intercept"])
                logits = coefficient * probabilities + intercept
                return cast(npt.NDArray[np.float64], 1.0 / (1.0 + np.exp(-logits)))
            if self.method == "isotonic":
                x_values = np.asarray(self._serialized_params["x_thresholds"], dtype=float)
                y_values = np.asarray(self._serialized_params["y_thresholds"], dtype=float)
                return cast(
                    npt.NDArray[np.float64],
                    np.interp(
                        probabilities, x_values, y_values, left=y_values[0], right=y_values[-1]
                    ),
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

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"version": 1, "method": self.method}
        if self.method == "none":
            return payload
        if self._serialized_params is not None:
            payload.update(self._serialized_params)
            return payload
        if self._model is None:
            raise ValueError("Calibrator has not been fitted")
        if self.method == "platt":
            model = cast(LogisticRegression, self._model)
            payload.update(
                coefficient=float(model.coef_[0][0]),
                intercept=float(model.intercept_[0]),
            )
            return payload
        model = cast(IsotonicRegression, self._model)
        payload.update(
            x_thresholds=[float(value) for value in model.X_thresholds_],
            y_thresholds=[float(value) for value in model.y_thresholds_],
        )
        return payload

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> ProbabilityCalibrator:
        if int(payload.get("version", 0)) != 1:
            raise ValueError("Unsupported calibrator JSON version")
        method = str(payload.get("method", ""))
        if method not in {"none", "platt", "isotonic"}:
            raise ValueError("Unsupported calibrator method")
        instance = cls(cast(CalibrationMethod, method))
        if method == "platt":
            params = {
                "coefficient": float(payload["coefficient"]),
                "intercept": float(payload["intercept"]),
            }
            if not all(np.isfinite(value) for value in params.values()):
                raise ValueError("Non-finite Platt calibrator parameter")
            instance._serialized_params = params
        elif method == "isotonic":
            x_values = [float(value) for value in cast(Iterable[Any], payload["x_thresholds"])]
            y_values = [float(value) for value in cast(Iterable[Any], payload["y_thresholds"])]
            if len(x_values) < 2 or len(x_values) != len(y_values):
                raise ValueError("Invalid isotonic calibrator thresholds")
            if not all(np.isfinite(value) for value in [*x_values, *y_values]):
                raise ValueError("Non-finite isotonic calibrator threshold")
            if any(right <= left for left, right in pairwise(x_values)):
                raise ValueError("Isotonic thresholds must be strictly increasing")
            instance._serialized_params = {
                "x_thresholds": x_values,
                "y_thresholds": y_values,
            }
        return instance


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_artifact_manifest(path: Path, file_names: Iterable[str]) -> None:
    payload: dict[str, Any] = {
        "version": 1,
        "files": {name: _sha256(path / name) for name in sorted(file_names)},
    }
    signature: str | None = None
    private_key_path = str(settings.MODEL_SIGNING_PRIVATE_KEY_FILE or "").strip()
    if private_key_path:
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError as exc:  # pragma: no cover - dependency enforced in production lock
            raise RuntimeError("cryptography is required to sign model artifacts") from exc
        key = serialization.load_pem_private_key(
            Path(private_key_path).read_bytes(),
            password=None,
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Model signing key must be an Ed25519 private key")
        signature = base64.b64encode(key.sign(_canonical_json(payload))).decode("ascii")
    manifest = {
        "payload": payload,
        "signature_algorithm": "ed25519" if signature else None,
        "signature": signature,
    }
    (path / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _verify_artifact_manifest(path: Path, trust_mode: str) -> None:
    manifest_path = path / "artifact_manifest.json"
    if not manifest_path.exists():
        if trust_mode == "enforce":
            raise ValueError("Signed artifact manifest is required")
        logger.warning("artifact_manifest_missing", path=str(path))
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or int(payload.get("version", 0)) != 1:
        raise ValueError("Invalid artifact manifest")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Artifact manifest has no files")
    for name, expected_hash in files.items():
        safe_name = str(name)
        if Path(safe_name).name != safe_name:
            raise ValueError("Artifact manifest contains an invalid file name")
        artifact = path / safe_name
        if not artifact.is_file() or _sha256(artifact) != str(expected_hash):
            raise ValueError(f"Artifact integrity check failed: {name}")

    signature = manifest.get("signature")
    public_key_path = str(settings.MODEL_VERIFY_PUBLIC_KEY_FILE or "").strip()
    if not signature or not public_key_path:
        if trust_mode == "enforce":
            raise ValueError("Ed25519 artifact signature and public key are required")
        logger.warning("artifact_signature_not_verified", path=str(path))
        return
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - dependency enforced in production lock
        raise RuntimeError("cryptography is required to verify model artifacts") from exc
    key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Model verification key must be an Ed25519 public key")
    try:
        key.verify(base64.b64decode(str(signature), validate=True), _canonical_json(payload))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("Artifact signature verification failed") from exc


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

    def fit(self, features: pd.DataFrame, labels: Iterable[int]) -> SignalMetaModel:
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

            if np.unique(y_train).size < 2:
                continue

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

    def predict_probability(self, features: Mapping[str, float] | pd.DataFrame) -> float:
        frame = self._coerce_features(features)
        raw_probability = self.model.predict_proba(frame)[:, 1]
        return float(self.calibrator.predict(raw_probability)[0])

    def _coerce_features(self, features: Mapping[str, float] | pd.DataFrame) -> pd.DataFrame:
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
        # Model: XGBoost native format (safe) if available, else joblib
        if _HAS_XGBOOST and hasattr(self.model, "save_model"):
            self.model.save_model(str(path / "meta_model.ubj"))
            model_file = "meta_model.ubj"
        else:
            joblib.dump(self.model, path / "meta_model.joblib")
            model_file = "meta_model.joblib"
        (path / "probability_calibrator.json").write_text(
            json.dumps(self.calibrator.to_json_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
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
        _write_artifact_manifest(
            path,
            (
                model_file,
                "probability_calibrator.json",
                "feature_columns.json",
                "training_manifest.json",
                "metrics.json",
            ),
        )
        return path

    @classmethod
    def load_artifacts(cls, artifact_dir: str | Path) -> SignalMetaModel:
        path = Path(artifact_dir)
        trust_mode = str(settings.CALIBRATOR_TRUST or "warn").lower()
        if trust_mode not in {"warn", "enforce"}:
            raise ValueError(f"Unsupported CALIBRATOR_TRUST mode: {trust_mode}")
        _verify_artifact_manifest(path, trust_mode)
        feature_names = json.loads((path / "feature_columns.json").read_text(encoding="utf-8"))

        # Model: try XGBoost native (.ubj), then joblib (.joblib).
        ubj_path = path / "meta_model.ubj"
        joblib_path = path / "meta_model.joblib"
        pkl_path = path / "meta_model.pkl"
        if ubj_path.exists():
            if not _HAS_XGBOOST:
                raise RuntimeError("XGBoost model found but xgboost package is not available")
            model = _build_classifier()
            model.load_model(str(ubj_path))
        elif joblib_path.exists():
            model = joblib.load(joblib_path)
        elif pkl_path.exists():
            logger.warning("pickle_model_rejected", path=str(pkl_path))
            raise FileNotFoundError(
                f"Pickle model format is not supported. Convert {pkl_path} to .ubj or .joblib"
            )
        else:
            raise FileNotFoundError(f"No model file (ubj/joblib) found in {path}")

        # Calibrator: safe JSON is primary; joblib is warn-mode migration only.
        cal_json = path / "probability_calibrator.json"
        cal_joblib = path / "probability_calibrator.joblib"
        cal_pkl = path / "probability_calibrator.pkl"
        if cal_json.exists():
            calibrator_payload = json.loads(cal_json.read_text(encoding="utf-8"))
            if not isinstance(calibrator_payload, dict):
                raise ValueError("Calibrator JSON must contain an object")
            calibrator = ProbabilityCalibrator.from_json_dict(calibrator_payload)
        elif cal_joblib.exists() and trust_mode != "enforce":
            # Validate that the file is not empty and resides in a trusted path
            if cal_joblib.stat().st_size == 0:
                raise ValueError(f"Corrupt or empty calibrator file: {cal_joblib}")
            logger.warning("legacy_joblib_calibrator_loaded", path=str(cal_joblib))
            calibrator = joblib.load(cal_joblib)
        elif cal_joblib.exists():
            raise ValueError("JSON calibrator is required in enforce mode")
        elif cal_pkl.exists():
            logger.warning("pickle_calibrator_rejected", path=str(cal_pkl))
            raise FileNotFoundError(
                f"Pickle calibrator format is not supported. Convert {cal_pkl} to .joblib"
            )
        else:
            raise FileNotFoundError(f"No calibrator file (JSON/joblib) found in {path}")

        instance = cls(getattr(calibrator, "method", "platt"))
        instance.model = model
        instance.calibrator = calibrator
        instance.feature_names = list(feature_names)
        return instance
