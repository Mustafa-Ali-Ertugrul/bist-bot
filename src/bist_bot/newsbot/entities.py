"""Haberlerde şirket/sembol varlık çıkarımı.

Sembol tanımları tek kaynaktan (config/newsbot_symbols.json) yüklenir;
aynı veri hem DB seed'inde hem çıkarımda kullanılır. Türkçe İ/ı/i
farkları ve diacritic'ler normalization_utils üzerinden giderilir.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from bist_bot.newsbot.utils import normalize_text

DEFAULT_SYMBOLS_PATH = "config/newsbot_symbols.json"


def load_symbols(path: str | None = None) -> dict[str, dict[str, Any]]:
    """JSON config dosyasından sembol sözlüğü yükler (symbol -> metadata)."""
    path = path or os.getenv("NEWSBOT_SYMBOLS_PATH", DEFAULT_SYMBOLS_PATH)
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    items = data.get("symbols", []) if isinstance(data, dict) else data

    symbols: dict[str, dict[str, Any]] = {}
    for item in items:
        symbol = str(item["symbol"]).upper()
        symbols[symbol] = {
            "symbol": symbol,
            "company_name": item.get("company_name", ""),
            "aliases": item.get("aliases", [symbol]),
            "sector": item.get("sector"),
        }
    return symbols


class EntityExtractor:
    """Başlık + içerikte şirket varlıklarını kelime sınırıyla tespit eder."""

    def __init__(self, symbols: dict[str, dict[str, Any]] | None = None) -> None:
        self.symbols = symbols if symbols is not None else load_symbols()
        self.patterns: dict[str, re.Pattern[str]] = {}
        for symbol, meta in self.symbols.items():
            aliases = [a for a in (normalize_text(a) for a in (meta.get("aliases") or [])) if a]
            if normalize_text(symbol) not in aliases:
                aliases.append(normalize_text(symbol))
            pattern = r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b"
            self.patterns[symbol] = re.compile(pattern)

    def extract_entities(self, title: str, content: str) -> list[dict[str, Any]]:
        """İçerikte eşleşen şirketleri döndürür (sembol bazında tekil).

        Her sonuç: symbol, company_name, match_type ("symbol"|"alias"),
        confidence (100|80), raw_match (normalize edilmiş eşleşen metin).
        """
        text = normalize_text(f"{title or ''} {content or ''}")
        found: dict[str, dict[str, Any]] = {}
        for symbol, pattern in self.patterns.items():
            match = pattern.search(text)
            if not match:
                continue
            meta = self.symbols[symbol]
            raw_match = match.group(0)
            is_symbol = raw_match.upper() == symbol
            found[symbol] = {
                "symbol": symbol,
                "company_name": meta["company_name"],
                "match_type": "symbol" if is_symbol else "alias",
                "confidence": 100 if is_symbol else 80,
                "raw_match": raw_match,
            }
        return list(found.values())

    def get_symbols_for_seed(self) -> list[dict[str, Any]]:
        """Seed'de kullanılmak üzere tüm sembol metadata'larını döndürür."""
        return list(self.symbols.values())
