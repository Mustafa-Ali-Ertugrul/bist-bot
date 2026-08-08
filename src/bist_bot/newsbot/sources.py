"""YAML tabanlı haber kaynakları yükleyici."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pyyaml bağımlılığı eksik. 'pip install PyYAML>=6.0.1' çalıştırın.") from exc


def load_sources(path: str | None = None) -> list[dict[str, Any]]:
    """
    Kaynak YAML dosyasını okur ve her kayıt için eksik alanlara default değerler atar.

    Default'lar:
        trust_score   → 70
        interval_seconds → 120
        active        → True
    """
    path = path or os.getenv("NEWSBOT_SOURCES_PATH", "config/newsbot_sources.yaml")
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    sources: list[dict[str, Any]] = data.get("sources", [])

    for s in sources:
        s.setdefault("trust_score", 70)
        s.setdefault("interval_seconds", 120)
        s.setdefault("active", True)

    return sources
