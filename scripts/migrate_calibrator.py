"""Convert a known-good legacy joblib calibrator to the safe JSON format.

This command intentionally requires an expected SHA-256 before deserializing.
It must only be used for artifacts whose provenance was established separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib

from bist_bot.ml.meta_model import ProbabilityCalibrator, _write_artifact_manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate(artifact_dir: Path, expected_sha256: str) -> Path:
    source = artifact_dir / "probability_calibrator.joblib"
    if not source.is_file():
        raise FileNotFoundError(f"Legacy calibrator not found: {source}")
    actual_sha256 = _sha256(source)
    if actual_sha256.lower() != expected_sha256.strip().lower():
        raise ValueError("Legacy calibrator SHA-256 does not match the approved value")

    calibrator = joblib.load(  # nosec B301: mandatory approved SHA-256 check above.
        source
    )
    if not isinstance(calibrator, ProbabilityCalibrator):
        raise TypeError("Legacy artifact is not a ProbabilityCalibrator")
    destination = artifact_dir / "probability_calibrator.json"
    destination.write_text(
        json.dumps(calibrator.to_json_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    provenance = artifact_dir / "calibrator_migration_provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "source": source.name,
                "source_sha256": actual_sha256,
                "converted_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    artifact_names = [
        name
        for name in (
            "meta_model.ubj",
            "meta_model.joblib",
            "probability_calibrator.json",
            "feature_columns.json",
            "training_manifest.json",
            "metrics.json",
            "calibrator_migration_provenance.json",
        )
        if (artifact_dir / name).is_file()
    ]
    _write_artifact_manifest(artifact_dir, artifact_names)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    output = migrate(args.artifact_dir, args.expected_sha256)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
