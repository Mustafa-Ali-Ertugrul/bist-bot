"""Calculate the documented AppSec score from finding status metadata."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

WEIGHTS = {
    "critical": 10.0,
    "high": 7.0,
    "medium": 4.0,
    "low": 1.5,
    "best_practice": 0.5,
}

# A finding leaves the open score only after it is fixed or explicitly accepted.
FINDINGS = [
    {"id": 1, "severity": "high", "status": "mitigated_warn", "title": "scan RBAC"},
    {"id": 2, "severity": "high", "status": "fixed", "title": "order idempotency"},
    {"id": 3, "severity": "high", "status": "mitigated_warn", "title": "joblib trust"},
    {"id": 4, "severity": "high", "status": "fixed", "title": "dependency lock"},
    {"id": 5, "severity": "medium", "status": "open", "title": "login rate limit"},
    {"id": 6, "severity": "medium", "status": "open", "title": "scan TOCTOU"},
    {"id": 7, "severity": "medium", "status": "open", "title": "quote plausibility"},
    {"id": 8, "severity": "medium", "status": "open", "title": "silent exceptions"},
    {"id": 9, "severity": "medium", "status": "open", "title": "Android WebView"},
    {"id": 10, "severity": "medium", "status": "open", "title": "health disclosure"},
    {"id": 11, "severity": "medium", "status": "open", "title": "gitignore coverage"},
    {"id": 12, "severity": "medium", "status": "open", "title": "compose credentials"},
    {"id": 13, "severity": "low", "status": "open", "title": "temporary CA bundle"},
    {"id": 14, "severity": "low", "status": "open", "title": "broker JSON validation"},
    {"id": 15, "severity": "low", "status": "open", "title": "RSS URL encoding"},
    {"id": 16, "severity": "low", "status": "open", "title": "ephemeral Cloud Run DB"},
    {"id": 17, "severity": "low", "status": "open", "title": "fetcher cache locking"},
    {"id": 18, "severity": "low", "status": "open", "title": "JWT revocation"},
    {"id": 19, "severity": "low", "status": "open", "title": "exception log redaction"},
    {"id": 20, "severity": "low", "status": "fixed", "title": "script SQL identifiers"},
    {"id": 21, "severity": "best_practice", "status": "open", "title": "nosec review"},
    {"id": 22, "severity": "best_practice", "status": "open", "title": "security headers"},
    {"id": 23, "severity": "best_practice", "status": "open", "title": "Telegram HTML escape"},
]


def calculate() -> dict[str, object]:
    baseline_score = sum(WEIGHTS[item["severity"]] for item in FINDINGS)
    open_findings = [item for item in FINDINGS if item["status"] not in {"fixed", "accepted"}]
    open_score = sum(WEIGHTS[item["severity"]] for item in open_findings)
    status_counts = Counter(str(item["status"]) for item in FINDINGS)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "weights": WEIGHTS,
        "baseline_score": baseline_score,
        "open_score": open_score,
        "finding_count": len(FINDINGS),
        "open_count": len(open_findings),
        "status_counts": dict(sorted(status_counts.items())),
        "findings": FINDINGS,
        "notes": [
            "mitigated_warn remains open until enforcement is deployed",
            "finding 2 is fail-closed when daily history is unavailable",
            "the historical leaked API key is tracked separately as an incident blocker",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(calculate(), indent=2, sort_keys=True), encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
