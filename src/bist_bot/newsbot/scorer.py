"""Haber katman sınıflandırma ve duygu skorlama motoru.

Katmanlar (newsbot_article_layers + newsbot_layer_scores tablolarına yazar):
  - stock     (Layer 1): haber doğrudan bir şirkete/sembole ilişkin
  - macro     (Layer 2): ekonomi/makro finans haberi
  - global    (Layer 3): küresel piyasa/geopolitik gelişme
  - uncategorized: eşleşen hiçbir katman yok — kayıt atlanır

Skor aralığı 1-10 (5 = nötr); yön ``positive`` / ``negative`` / ``neutral``.
Formül: `score = clamp(1, 10, 5 + 2 * (pozitif_vuruş - negatif_vuruş))`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from bist_bot.app_logging import get_logger
from bist_bot.newsbot.utils import normalize_text

logger = get_logger("newsbot.scorer")

DEFAULT_KEYWORDS_PATH = "config/newsbot_keywords.json"


def load_keywords(path: str | None = None) -> dict[str, Any]:
    """JSON config dosyasından keyword sözlüğünü yükler."""
    path = path or os.getenv("NEWSBOT_KEYWORDS_PATH", DEFAULT_KEYWORDS_PATH)
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    return data


def classify_layer(
    title: str,
    content: str,
    entities: list[dict],
    layer_triggers: dict[str, list[str]],
) -> str:
    """Haberin hangi katmanda olduğunu sınıflandırır.

    Öncelik kuralı (kararlı): entity öncelikli → macro trigger → global trigger.
    """
    # Layer 1 (stock) — entity tespit edildi mi?
    if entities:
        return "stock"

    norm_text = normalize_text(f"{title or ''} {content or ''}")

    # Layer 2 (macro)
    for trigger in layer_triggers.get("macro", []):
        pattern = r"\b" + re.escape(normalize_text(trigger)) + r"\b"
        if re.search(pattern, norm_text):
            return "macro"

    # Layer 3 (global)
    for trigger in layer_triggers.get("global", []):
        pattern = r"\b" + re.escape(normalize_text(trigger)) + r"\b"
        if re.search(pattern, norm_text):
            return "global"

    return "uncategorized"


def calculate_score(
    title: str,
    content: str,
    layer: str,
    keywords: dict[str, Any],
) -> tuple[int, str, dict[str, list[str]]]:
    """Haberin duygu skorunu hesaplar (1-10 arası, 5 nötr).

    Döner: ``(score, direction, matched_keywords)``
    """
    norm_text = normalize_text(f"{title or ''} {content or ''}")
    layer_kw = keywords.get("layers", {}).get(layer, {})
    pos_kw = layer_kw.get("positive", [])
    neg_kw = layer_kw.get("negative", [])

    pos_matches = [
        kw for kw in pos_kw if re.search(r"\b" + re.escape(normalize_text(kw)) + r"\b", norm_text)
    ]
    neg_matches = [
        kw for kw in neg_kw if re.search(r"\b" + re.escape(normalize_text(kw)) + r"\b", norm_text)
    ]

    diff = len(pos_matches) - len(neg_matches)
    score = max(1, min(10, 5 + 2 * diff))

    if score > 5:
        direction = "positive"
    elif score < 5:
        direction = "negative"
    else:
        direction = "neutral"

    return score, direction, {"positive": pos_matches, "negative": neg_matches}


def save_layer_scores(
    session: Session,
    article_id: int,
    layer: str,
    score: int,
    direction: str,
    matched_keywords: dict[str, list[str]],
    symbol_id: int | None = None,
) -> None:
    """Katman ve skorları DB'ye yazar (article_layers + layer_scores)."""
    if layer == "uncategorized":
        logger.debug("layer_uncategorized", article_id=article_id)
        return

    keywords_json = json.dumps(matched_keywords, ensure_ascii=False)

    session.execute(
        text(
            """
            INSERT INTO newsbot_article_layers
                (article_id, layer, primary_layer, confidence)
            VALUES (:article_id, :layer, 1, 100)
            """
        ),
        {"article_id": article_id, "layer": layer},
    )

    session.execute(
        text(
            """
            INSERT INTO newsbot_layer_scores
                (article_id, layer, symbol_id, scope, direction, score_1_10, impact_level, confidence, keywords_json)
            VALUES (:article_id, :layer, :symbol_id, :scope, :direction, :score, :impact, 100, :keywords_json)
            """
        ),
        {
            "article_id": article_id,
            "layer": layer,
            "symbol_id": symbol_id,
            "scope": layer,
            "direction": direction,
            "score": score,
            "impact": _impact_level(score),
            "keywords_json": keywords_json,
        },
    )


def _impact_level(score: int) -> str:
    """Skor aralığına göre etki seviyesi döndürür."""
    if score <= 3 or score >= 8:
        return "high"
    if score == 4 or score == 7:
        return "medium"
    return "low"
