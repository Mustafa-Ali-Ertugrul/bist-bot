from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.ml import ProbabilityCalibrator, SignalMetaModel
from bist_bot.ml.features import to_float
from bist_bot.ml.meta_model import _verify_artifact_manifest, _write_artifact_manifest


def test_probability_calibrator_platt_outputs_bounded_values() -> None:
    calibrator = ProbabilityCalibrator("platt")
    calibrator.fit([0.15, 0.3, 0.45, 0.7, 0.9], [0, 0, 0, 1, 1])

    predictions = calibrator.predict([0.2, 0.8])

    assert 0.0 <= predictions[0] <= 1.0
    assert 0.0 <= predictions[1] <= 1.0
    assert predictions[1] > predictions[0]


def test_signal_meta_model_fit_and_predict_probability() -> None:
    features = pd.DataFrame(
        {
            "score": [10, 15, 20, 40, 55, 65, 75, 85, 25, 35],
            "adx": [15, 17, 18, 22, 28, 30, 35, 40, 20, 24],
            "rsi": [42, 45, 48, 52, 55, 58, 62, 66, 50, 54],
            "volume_ratio": [0.9, 1.0, 1.05, 1.1, 1.3, 1.5, 1.7, 1.9, 1.15, 1.2],
        }
    )
    labels = [0, 0, 0, 0, 1, 1, 1, 1, 0, 1]
    model = SignalMetaModel(
        calibration_method="platt",
        n_cv_splits=3,
    )

    model.fit(features, labels)
    probability = model.predict_probability(
        {"score": 70.0, "adx": 32.0, "rsi": 61.0, "volume_ratio": 1.6}
    )

    assert 0.0 <= probability <= 1.0


def test_to_float_uses_default_for_missing_and_non_finite_values() -> None:
    assert to_float(None, default=7.0) == 7.0
    assert to_float(np.nan, default=7.0) == 7.0
    assert to_float(pd.NA, default=7.0) == 7.0
    assert to_float("bad", default=7.0) == 7.0
    assert to_float(3.5, default=7.0) == 3.5
    assert math.isfinite(to_float("3.5", default=7.0))


def test_signal_meta_model_rejects_pickle_artifacts(tmp_path) -> None:
    (tmp_path / "feature_columns.json").write_text(json.dumps(["score"]), encoding="utf-8")
    (tmp_path / "meta_model.pkl").write_bytes(b"not-a-safe-artifact")
    (tmp_path / "probability_calibrator.joblib").write_bytes(b"not-used")

    with pytest.raises(FileNotFoundError, match="Pickle model format is not supported"):
        SignalMetaModel.load_artifacts(tmp_path)


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_calibrator_json_round_trip_preserves_probabilities(method) -> None:
    calibrator = ProbabilityCalibrator(method)
    calibrator.fit([0.05, 0.2, 0.4, 0.6, 0.8, 0.95], [0, 0, 0, 1, 1, 1])
    samples = [0.1, 0.35, 0.7, 0.9]

    restored = ProbabilityCalibrator.from_json_dict(calibrator.to_json_dict())

    np.testing.assert_allclose(
        restored.predict(samples),
        calibrator.predict(samples),
        rtol=0.0,
        atol=1e-9,
    )


def test_enforce_mode_rejects_unsigned_artifacts(tmp_path) -> None:
    (tmp_path / "feature_columns.json").write_text('["score"]', encoding="utf-8")

    with settings.override(CALIBRATOR_TRUST="enforce"):
        with pytest.raises(ValueError, match="Signed artifact manifest is required"):
            SignalMetaModel.load_artifacts(tmp_path)


def test_artifact_trust_cannot_be_disabled(tmp_path) -> None:
    with settings.override(CALIBRATOR_TRUST="off"):
        with pytest.raises(ValueError, match="Unsupported CALIBRATOR_TRUST mode"):
            SignalMetaModel.load_artifacts(tmp_path)


def test_ed25519_manifest_verifies_and_detects_tampering(tmp_path) -> None:
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _ = cryptography
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    artifact = tmp_path / "safe.json"
    artifact.write_text('{"ok":true}', encoding="utf-8")
    with settings.override(MODEL_SIGNING_PRIVATE_KEY_FILE=str(private_path)):
        _write_artifact_manifest(tmp_path, ["safe.json"])
    with settings.override(MODEL_VERIFY_PUBLIC_KEY_FILE=str(public_path)):
        _verify_artifact_manifest(tmp_path, "enforce")

        artifact.write_text('{"ok":false}', encoding="utf-8")
        with pytest.raises(ValueError, match="integrity check failed"):
            _verify_artifact_manifest(tmp_path, "enforce")
