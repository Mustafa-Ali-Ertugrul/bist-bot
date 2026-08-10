"""EntityExtractor testleri — sembol/alias eşleştirme ve Türkçe normalizasyon."""

from __future__ import annotations

from pathlib import Path

import pytest

from bist_bot.newsbot.entities import EntityExtractor, load_symbols

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "newsbot_symbols.json"


@pytest.fixture()
def extractor() -> EntityExtractor:
    return EntityExtractor(load_symbols(str(_CONFIG_PATH)))


def test_load_symbols_from_config() -> None:
    """Config JSON 22 BIST sembolü içerir ve yüklenir."""
    symbols = load_symbols(str(_CONFIG_PATH))
    assert len(symbols) == 22
    # Hepsini içermeli
    expected_all = {
        "THYAO", "ASELS", "GARAN", "KCHOL", "FROTO", "TUPRS", "BIMAS",
        "EREGL", "AKBNK", "ISCTR",
        "HALKB", "VAKBN", "YKBNK", "SASA", "PGSUS", "TOASO",
        "SAHOL", "PETKM", "MGROS", "SOKM", "TCELL", "ENKAI",
    }
    assert set(symbols) == expected_all


def test_symbol_exact_match(extractor: EntityExtractor) -> None:
    """Tam sembol kodu eşleşince match_type=symbol, confidence=100."""
    entities = extractor.extract_entities("THYAO bilanço açıkladı", "Şirket kârını duyurdu")
    assert len(entities) == 1
    entity = entities[0]
    assert entity["symbol"] == "THYAO"
    assert entity["match_type"] == "symbol"
    assert entity["confidence"] == 100


def test_alias_match(extractor: EntityExtractor) -> None:
    """Alias eşleşince match_type=alias, confidence=80."""
    entities = extractor.extract_entities("THY kar açıkladı", "Uçuş gelirleri arttı")
    assert len(entities) == 1
    entity = entities[0]
    assert entity["symbol"] == "THYAO"
    assert entity["match_type"] == "alias"
    assert entity["confidence"] == 80


def test_case_insensitive(extractor: EntityExtractor) -> None:
    """Büyük-küçük harf farkı eşleşmeyi etkilemez."""
    entities = extractor.extract_entities("thy yeni rota açtı", "kapasite artıyor")
    assert {e["symbol"] for e in entities} == {"THYAO"}


def test_word_boundary(extractor: EntityExtractor) -> None:
    """Kısmi sembol/kelime eşleşmez: ASEL, ASE veya ASELSAN'ın parçası değil."""
    assert extractor.extract_entities("ASEL yatırım yaptı", "") == []
    assert extractor.extract_entities("ASE endeksi yükseldi", "") == []
    entities = extractor.extract_entities("ASELSAN yeni sözleşme imzaladı", "")
    assert {e["symbol"] for e in entities} == {"ASELS"}


def test_multiple_symbols_deduplicated(extractor: EntityExtractor) -> None:
    """Birden çok şirket tespit edilir; aynı şirket tekil döner."""
    entities = extractor.extract_entities(
        "THYAO ve GARAN kâr açıkladı",
        "THYAO net kârını duyurdu, Garanti bankası da güçlü sonuçlar bildirdi",
    )
    symbols = [e["symbol"] for e in entities]
    assert symbols == ["THYAO", "GARAN"]
    assert len(symbols) == len(set(symbols))


def test_turkish_character_normalization(extractor: EntityExtractor) -> None:
    """İ/ı/i yazım varyasyonları aynı sembole eşlenir."""
    variants = [
        "İş Bankası kâr açıkladı",
        "iş bankasi kar açikladi",
        "IŞ BANKASI KÂR AÇIKLADI",
    ]
    for text in variants:
        entities = extractor.extract_entities(text, "")
        assert [e["symbol"] for e in entities] == ["ISCTR"], text


def test_no_match_returns_empty(extractor: EntityExtractor) -> None:
    """İlgisiz haberlerde entity dönmez."""
    entities = extractor.extract_entities(
        "Enflasyon verileri açıklandı", "TÜİK istatistik yayınladı"
    )
    assert entities == []
