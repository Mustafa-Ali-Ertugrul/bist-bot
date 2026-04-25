"""Persisted Streamlit/UI user preferences store."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / "user_settings.json"

DEFAULT_SETTINGS = {
    "indicator": {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "sma_fast": 5,
        "sma_slow": 20,
        "ema_fast": 12,
        "ema_slow": 26,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std": 2.0,
        "adx_threshold": 20,
    },
    "telegram": {
        "bot_token": "",
        "chat_id": "",
        "notify_min_score": 30,
        "enabled": False,
    },
    "scan": {
        "auto_refresh": False,
        "refresh_interval": 5,
        "min_score_filter": -100,
        "rsi_min_filter": 0,
        "rsi_max_filter": 100,
        "vol_ratio_filter": 0.0,
    },
}


def _deepcopy_defaults() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS)


def _merge_with_defaults(data: dict | None) -> dict:
    merged = _deepcopy_defaults()
    if not isinstance(data, dict):
        return merged
    for section, defaults in merged.items():
        current = data.get(section, {})
        if not isinstance(current, dict):
            continue
        defaults.update(current)
    merged["telegram"]["bot_token"] = ""
    merged["telegram"]["chat_id"] = ""
    return merged


def load_settings() -> dict:
    """Load persisted UI preferences while preserving legacy JSON shape."""
    try:
        if not CONFIG_FILE.exists():
            return _deepcopy_defaults()
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return _merge_with_defaults(data)
    except Exception as e:
        logger.warning(f"Settings load failed: {e}, using defaults")
        return _deepcopy_defaults()


def save_settings(settings: dict) -> bool:
    """Save persisted UI preferences while stripping secret inputs."""
    try:
        settings = _merge_with_defaults(json.loads(json.dumps(settings)))
        telegram = settings["telegram"]
        telegram["bot_token"] = ""
        telegram["chat_id"] = ""
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Settings save failed: {e}")
        return False


def reset_settings() -> bool:
    """Reset persisted UI preferences."""
    try:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        return True
    except Exception as e:
        logger.error(f"Settings reset failed: {e}")
        return False


def get_indicator_defaults() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS["indicator"])


def get_telegram_settings() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS["telegram"])


def get_scan_settings() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS["scan"])
