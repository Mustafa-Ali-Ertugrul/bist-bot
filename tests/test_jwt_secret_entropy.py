"""AppSec R6: JWT secret entropy enforcement regression guard.

`settings.require_security_config` HS256 anahtarına karsi brute-force savunu
olarak minimum uzunluk zorlar: CONFIG_STRICT=true altinda 32 karakter alti
fail-closed, dev modunda uyar. Testler settings.override() kullanir —
module reload'a gerek yok, singleton temiz kalir.
"""

import pytest

from bist_bot.config.settings import Settings, settings


def test_short_jwt_secret_fails_closed_in_strict_mode(monkeypatch):
    monkeypatch.setenv("CONFIG_STRICT", "true")
    with settings.override(JWT_SECRET_KEY="short"):
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY en az 32 karakter"):
            settings.require_security_config()


def test_short_jwt_secret_warns_in_dev_mode(monkeypatch):
    monkeypatch.setenv("CONFIG_STRICT", "false")
    with settings.override(JWT_SECRET_KEY="short"):
        with pytest.warns(UserWarning, match="32 karakterden kisa"):
            settings.require_security_config()


def test_placeholder_jwt_secret_still_rejected():
    with settings.override(JWT_SECRET_KEY="change-me"):
        with pytest.raises(RuntimeError, match="known placeholder"):
            settings.require_security_config()


def test_long_jwt_secret_passes(monkeypatch):
    monkeypatch.setenv("CONFIG_STRICT", "true")
    with settings.override(JWT_SECRET_KEY="x" * 32):
        # 32 karakterlik ozel-deger blacklist'e dusmediginden sorunsuz gecer.
        settings.require_security_config()


def test_missing_jwt_secret_rejected():
    with settings.override(JWT_SECRET_KEY=""):
        with pytest.raises(RuntimeError, match="Missing required security setting"):
            settings.require_security_config()


def test_default_settings_instance_is_consistent():
    # Singleton Settings class-level alanlariyla ayni degeri tasiyor olmali;
    # import-time env okuma bozulmadigini dogrular.
    fresh = Settings()
    assert fresh.JWT_SECRET_KEY == settings.JWT_SECRET_KEY
