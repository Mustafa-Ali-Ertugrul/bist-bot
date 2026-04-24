"""Config and config_store tests."""

from __future__ import annotations

import importlib
import json
import os
import sys

import dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def test_flask_debug_default_false(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    config_settings = importlib.import_module("bist_bot.config.settings")
    reloaded = importlib.reload(config_settings)
    assert reloaded.settings.FLASK_DEBUG is False


def test_flask_debug_env_override(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "True")
    sub = importlib.import_module("bist_bot.config.subsettings")
    importlib.reload(sub)
    config_settings = importlib.import_module("bist_bot.config.settings")
    reloaded = importlib.reload(config_settings)
    assert reloaded.settings.FLASK_DEBUG is True


def test_flask_port_prefers_cloud_run_port(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("FLASK_PORT", "5000")

    sub = importlib.import_module("bist_bot.config.subsettings")
    importlib.reload(sub)
    config_settings = importlib.import_module("bist_bot.config.settings")
    reloaded = importlib.reload(config_settings)

    assert reloaded.settings.FLASK_PORT == 8080
    assert reloaded.settings.API_BASE_URL == "http://localhost:8080"


def test_save_settings_strips_telegram_secrets(tmp_path, monkeypatch):
    from bist_bot.config import store as config_store

    monkeypatch.setattr(config_store, "CONFIG_FILE", tmp_path / "user_settings.json")

    settings = config_store.DEFAULT_SETTINGS.copy()
    settings["telegram"] = {
        "bot_token": "secret-token",
        "chat_id": "secret-chat",
        "notify_min_score": 55,
        "enabled": True,
    }

    assert config_store.save_settings(settings) is True

    loaded = config_store.load_settings()
    assert loaded["telegram"]["bot_token"] == ""
    assert loaded["telegram"]["chat_id"] == ""
    assert loaded["telegram"]["notify_min_score"] == 55
    assert loaded["telegram"]["enabled"] is True


def test_load_settings_merges_persisted_ui_preferences(tmp_path, monkeypatch):
    from bist_bot.config import store as config_store

    config_file = tmp_path / "user_settings.json"
    monkeypatch.setattr(config_store, "CONFIG_FILE", config_file)
    config_file.write_text(
        json.dumps(
            {
                "indicator": {"rsi_period": 21},
                "scan": {"refresh_interval": 15},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = config_store.load_settings()

    assert loaded["indicator"]["rsi_period"] == 21
    assert (
        loaded["indicator"]["adx_threshold"]
        == config_store.DEFAULT_SETTINGS["indicator"]["adx_threshold"]
    )
    assert loaded["scan"]["refresh_interval"] == 15
    assert (
        loaded["telegram"]["enabled"]
        == config_store.DEFAULT_SETTINGS["telegram"]["enabled"]
    )


def test_reset_settings_removes_persisted_file(tmp_path, monkeypatch):
    from bist_bot.config import store as config_store

    config_file = tmp_path / "user_settings.json"
    monkeypatch.setattr(config_store, "CONFIG_FILE", config_file)
    config_file.write_text("{}", encoding="utf-8")

    assert config_store.reset_settings() is True
    assert not config_file.exists()


def test_settings_override_uses_fast_merged_view() -> None:
    from bist_bot.config.settings import settings

    original = settings.BUY_THRESHOLD

    with settings.override(BUY_THRESHOLD=11):
        assert settings.BUY_THRESHOLD == 11
        with settings.override(SELL_THRESHOLD=-33):
            assert settings.BUY_THRESHOLD == 11
            assert settings.SELL_THRESHOLD == -33

    assert settings.BUY_THRESHOLD == original


def test_secret_settings_can_be_loaded_from_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "jwt_secret.txt"
    secret_file.write_text("file-based-secret\n", encoding="utf-8")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY_FILE", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY_FILE", str(secret_file))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    sub = importlib.import_module("bist_bot.config.subsettings")
    importlib.reload(sub)
    config_settings = importlib.import_module("bist_bot.config.settings")
    reloaded = importlib.reload(config_settings)

    assert reloaded.settings.JWT_SECRET_KEY == "file-based-secret"
