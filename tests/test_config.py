"""Config and config_store tests."""

from __future__ import annotations

import importlib
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def test_flask_debug_default_false(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    config_settings = importlib.import_module("config.settings")
    reloaded = importlib.reload(config_settings)
    assert reloaded.settings.FLASK_DEBUG is False


def test_flask_debug_env_override(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "True")
    config_settings = importlib.import_module("config.settings")
    reloaded = importlib.reload(config_settings)
    assert reloaded.settings.FLASK_DEBUG is True


def test_save_settings_strips_telegram_secrets(tmp_path, monkeypatch):
    import config_store

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
