"""Layer classifier + keyword scorer testleri."""

from __future__ import annotations

from pathlib import Path

import pytest

from bist_bot.newsbot.scorer import (
    calculate_score,
    classify_layer,
    load_keywords,
)

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "newsbot_keywords.json"


@pytest.fixture()
def keywords():
    return load_keywords(str(_CONFIG_PATH))


def test_classify_layer_1_with_entity(keywords):
    """Entity tespit edilirse Layer 1 (stock) döner."""
    entities = [
        {
            "symbol": "THYAO",
            "company_name": "Turk Hava Yollari",
            "match_type": "symbol",
            "confidence": 100,
            "raw_match": "thyao",
        }
    ]
    layer = classify_layer("THYAO bilanço açıkladı", "", entities, keywords["layer_triggers"])
    assert layer == "stock"


def test_classify_layer_2_macro_trigger(keywords):
    """Macro trigger (TCMB/para politikası) Layer 2'ye taşır."""
    entities = []
    layer = classify_layer("TCMB faiz kararını açıkladı", "", entities, keywords["layer_triggers"])
    assert layer == "macro"


def test_classify_layer_3_global_trigger(keywords):
    """Global trigger (Fed/Çin) Layer 3'e taşır."""
    entities = []
    layer = classify_layer("Fed faiz kararı bekleniyor", "", entities, keywords["layer_triggers"])
    assert layer == "global"


def test_classify_layer_3_others(keywords):
    """Daha az bariz global triggerlar da çalışır."""
    entities = []
    layer = classify_layer(
        "ABD seçim sonuçları piyasa etkiledi", "", entities, keywords["layer_triggers"]
    )
    assert layer == "global"


def test_layer_priority_entity_over_macro(keywords):
    """Entity + macro trigger bir arada — entity önceliklidir (Layer 1)."""
    entities = [
        {
            "symbol": "ASELS",
            "match_type": "symbol",
            "confidence": 100,
            "raw_match": "asels",
            "company_name": "Aselsan",
        }
    ]
    layer = classify_layer(
        "TCMB faiz kararı açıkladı, ASELS kâr açıkladı", "", entities, keywords["layer_triggers"]
    )
    assert layer == "stock"


def test_calculate_score_positive(keywords):
    """Pozitif keyword içerikli haber skor 7-10 arasıdır."""
    score, direction, matched = calculate_score("THYAO kâr artışı açıkladı", "", "stock", keywords)
    assert score >= 7
    assert direction == "positive"
    assert len(matched["positive"]) > 0
    assert len(matched["negative"]) == 0


def test_calculate_score_negative(keywords):
    """Negatif keyword içerikli haber skor 1-3 arasıdır."""
    score, direction, matched = calculate_score(
        "Şirket zarar etti ve soruşturma başlatıldı", "", "stock", keywords
    )
    assert score <= 3
    assert direction == "negative"
    assert len(matched["negative"]) > 0
    assert len(matched["positive"]) == 0


def test_calculate_score_neutral(keywords):
    """Keyword eşleşmeyen haber nötr (skor 5) döner."""
    score, direction, matched = calculate_score(
        "Haber metni sade bir duyuru içeriyor", "", "stock", keywords
    )
    assert score == 5
    assert direction == "neutral"
    assert len(matched["positive"]) == 0
    assert len(matched["negative"]) == 0


def test_turkish_diacritic_keyword_match(keywords):
    """Türkçe karakter varyantları keyword eşleşmesini bozmaz."""
    # "kâr artışı" keywoard'ı: "karartisi" veya "kâr artışi" gibi varyantlar
    score, _, _ = calculate_score("şirket kar artisi açıkladi", "", "stock", keywords)
    assert score > 5
    assert len(keywords["layers"]["stock"]["positive"]) > 0
