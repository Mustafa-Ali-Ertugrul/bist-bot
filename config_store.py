import json
import os
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


def load_settings() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for section, defaults in DEFAULT_SETTINGS.items():
            if section not in data:
                data[section] = defaults.copy()
            else:
                for key, value in defaults.items():
                    if key not in data[section]:
                        data[section][key] = value

        if "telegram" in data:
            data["telegram"]["bot_token"] = ""
            data["telegram"]["chat_id"] = ""

        return data
    except Exception as e:
        logger.warning(f"Settings load failed: {e}, using defaults")
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> bool:
    try:
        settings = json.loads(json.dumps(settings))
        telegram = settings.setdefault("telegram", {})
        telegram["bot_token"] = ""
        telegram["chat_id"] = ""

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Settings save failed: {e}")
        return False


def reset_settings() -> bool:
    try:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        return True
    except Exception as e:
        logger.error(f"Settings reset failed: {e}")
        return False


def get_indicator_defaults() -> dict:
    return load_settings().get("indicator", DEFAULT_SETTINGS["indicator"]).copy()


def get_telegram_settings() -> dict:
    return load_settings().get("telegram", DEFAULT_SETTINGS["telegram"]).copy()


def get_scan_settings() -> dict:
    return load_settings().get("scan", DEFAULT_SETTINGS["scan"]).copy()
