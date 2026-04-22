"""Tests for i18n/locale system."""

import pytest

from bist_bot.locales import get_message, set_default_locale, get_available_locales, _catalogs
from bist_bot.strategy.signal_models import SignalType


class TestLocales:
    def test_get_message_tr_default(self):
        msg = get_message("signal.buy")
        assert msg == "🟢 AL"

    def test_get_message_en(self):
        msg = get_message("signal.buy", locale="en")
        assert msg == "🟢 BUY"

    def test_get_message_fallback_unknown_key(self):
        msg = get_message("unknown.key", locale="en")
        assert msg == "unknown.key"

    def test_get_message_with_params(self):
        msg = get_message("log.scanning_stocks", locale="tr", count=5)
        assert "5" in msg
        assert "hisse" in msg

    def test_locale_fallback_unknown_locale(self):
        msg = get_message("signal.buy", locale="xx")
        assert msg == "🟢 AL"

    def test_set_default_locale(self):
        original = _catalogs.get("en", {}).get("signal.sell")
        set_default_locale("tr")
        msg = get_message("signal.sell")
        assert "SAT" in msg

    def test_get_available_locales(self):
        locales = get_available_locales()
        assert "tr" in locales
        assert "en" in locales


class TestSignalTypeI18n:
    def test_signal_type_display_tr(self):
        st = SignalType.BUY
        assert st.display == "🟢 AL"

    def test_signal_type_display_en_with_locale(self):
        set_default_locale("en")
        st = SignalType.BUY
        assert st.display == "🟢 BUY"
        set_default_locale("tr")
        assert st.display == "🟢 AL"

    def test_signal_type_value_backward_compat(self):
        st = SignalType.BUY
        assert "AL" in st.value or "Buy" in st.value

    def test_signal_type_key(self):
        st = SignalType.BUY
        assert st.key == "signal.buy"

    def test_confidence_display(self):
        assert get_message("confidence.low") == "DÜŞÜK"
        assert get_message("confidence.high") == "YÜKSEK"