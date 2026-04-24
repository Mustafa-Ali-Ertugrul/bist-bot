from __future__ import annotations

import pandas as pd

from bist_bot.ml import ProbabilityCalibrator, SignalMetaModel


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
        calibration_method="platt", n_cv_splits=3,
    )

    model.fit(features, labels)
    probability = model.predict_probability(
        {"score": 70.0, "adx": 32.0, "rsi": 61.0, "volume_ratio": 1.6}
    )

    assert 0.0 <= probability <= 1.0

