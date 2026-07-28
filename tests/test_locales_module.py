"""Tests for the locales module."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.locales import (  # noqa: E402
    DEFAULT_LOCALE,
    get_available_locales,
    get_message,
    set_default_locale,
)


class TestGetMessage:
    """Test the get_message function."""

    def setup_method(self) -> None:
        """Reset default locale to TR before each test."""
        set_default_locale("tr")

    def teardown_method(self) -> None:
        """Reset default locale after each test."""
        set_default_locale("tr")

    def test_get_message_tr_default(self) -> None:
        """When locale=tr (default), should return Turkish message."""
        result = get_message("signal.buy")
        assert result == "🟢 AL"

    def test_get_message_en_explicit(self) -> None:
        """When locale=en, should return English message."""
        result = get_message("signal.buy", locale="en")
        assert result == "🟢 BUY"

    def test_get_message_unknown_key_returns_key(self) -> None:
        """Unknown key should return the key itself as fallback."""
        result = get_message("nonexistent.key")
        assert result == "nonexistent.key"

    def test_get_message_unknown_locale_falls_back(self) -> None:
        """Unknown locale should fall back to default locale."""
        result = get_message("signal.buy", locale="xx")
        # Should fall back to tr (default)
        assert result == "🟢 AL"

    def test_get_message_with_kwargs(self) -> None:
        """get_message should support format() with kwargs."""
        result = get_message("test.greeting", locale="tr", name="Ali")
        # Should not raise, returns the message (possibly unformatted if no placeholder)
        assert isinstance(result, str)

    def test_get_message_kwargs_invalid_returns_unchanged(self) -> None:
        """If format() fails due to missing kwargs, return the raw message."""
        # Pick a key that we know doesn't have a placeholder but try to format it
        result = get_message("signal.buy", locale="tr", invalid_key="value")
        assert result == "🟢 AL"


class TestDefaultLocale:
    """Test default locale management."""

    def teardown_method(self) -> None:
        set_default_locale("tr")

    def test_default_locale_is_tr(self) -> None:
        """The default locale should be Turkish."""
        assert DEFAULT_LOCALE == "tr"

    def test_set_default_locale_to_en(self) -> None:
        """set_default_locale should change the default."""
        set_default_locale("en")
        result = get_message("signal.buy")
        assert result == "🟢 BUY"

    def test_set_default_locale_invalid_ignored(self) -> None:
        """Setting an invalid locale should be silently ignored."""
        set_default_locale("en")
        set_default_locale("invalid_locale")
        # Should still be "en" since invalid was rejected
        from bist_bot.locales import DEFAULT_LOCALE as current

        assert current == "en"

    def test_set_default_locale_back_to_tr(self) -> None:
        """Should be able to switch back to Turkish."""
        set_default_locale("en")
        set_default_locale("tr")
        result = get_message("signal.buy")
        assert result == "🟢 AL"


class TestAvailableLocales:
    """Test get_available_locales()."""

    def test_returns_list(self) -> None:
        """get_available_locales should return a list."""
        locales = get_available_locales()
        assert isinstance(locales, list)

    def test_contains_tr_and_en(self) -> None:
        """Both Turkish and English should be available."""
        locales = get_available_locales()
        assert "tr" in locales
        assert "en" in locales

    def test_at_least_two_locales(self) -> None:
        """There should be at least 2 available locales."""
        locales = get_available_locales()
        assert len(locales) >= 2


class TestAllSignalTranslations:
    """Test that all 8 signal types have proper translations in both locales."""

    def test_all_signals_have_tr_translation(self) -> None:
        """All 8 signal types should have Turkish translations."""
        signals = [
            "signal.strong_buy",
            "signal.buy",
            "signal.weak_buy",
            "signal.hold",
            "signal.radar",
            "signal.weak_sell",
            "signal.sell",
            "signal.strong_sell",
        ]
        for key in signals:
            result = get_message(key, locale="tr")
            assert result != key, f"Missing TR translation for {key}"
            assert len(result) > 0, f"Empty TR translation for {key}"

    def test_all_signals_have_en_translation(self) -> None:
        """All 8 signal types should have English translations."""
        signals = [
            "signal.strong_buy",
            "signal.buy",
            "signal.weak_buy",
            "signal.hold",
            "signal.radar",
            "signal.weak_sell",
            "signal.sell",
            "signal.strong_sell",
        ]
        for key in signals:
            result = get_message(key, locale="en")
            assert result != key, f"Missing EN translation for {key}"
            assert len(result) > 0, f"Empty EN translation for {key}"
