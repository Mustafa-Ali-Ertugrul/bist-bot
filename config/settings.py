from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data.bist100 import BIST100_TICKERS

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


CONFIG_DIR = Path(__file__).parent.parent
CONFIG_FILE = CONFIG_DIR / "user_settings.json"


logger = logging.getLogger(__name__)


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_str_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


DEFAULT_BIST100_WATCHLIST = BIST100_TICKERS

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

TICKER_NAMES = {
    "THYAO.IS": "THY",
    "ASELS.IS": "ASELSAN",
    "SASA.IS": "SASA",
    "KCHOL.IS": "Koç Holding",
    "EREGL.IS": "Ereğli",
    "BIMAS.IS": "BİM",
    "TUPRS.IS": "Tüpraş",
    "SAHOL.IS": "Sabancı Holding",
    "GARAN.IS": "Garanti BBVA",
    "TAVHL.IS": "TAV Havalimanları",
    "TOASO.IS": "Tofaş",
    "FROTO.IS": "Ford Otosan",
    "PETKM.IS": "Petkim",
    "KRDMD.IS": "Kardemir",
    "HEKTS.IS": "Hektaş",
    "AYGAZ.IS": "Aygaz",
    "ISCTR.IS": "İş Bankası",
    "YKBNK.IS": "Yapı Kredi",
    "HALKB.IS": "Halkbank",
    "VAKBN.IS": "VakıfBank",
    "AKSA.IS": "Aksa",
    "ARCLK.IS": "Arçelik",
    "CCOLA.IS": "Coca-Cola İçecek",
    "CIMSA.IS": "Çimsa",
    "CLEBI.IS": "Clebi",
    "ENJSA.IS": "Enerjisa Enerji",
    "ERBOS.IS": "Erbos",
    "FENIS.IS": "Feniş",
    "FMIZP.IS": "Formpi",
    "FORMT.IS": "Formet",
    "GENTS.IS": "Gents",
    "GLYHO.IS": "Gülho",
    "IPEKE.IS": "İpek",
    "IZMDC.IS": "İzdemir",
    "KARSN.IS": "Karsan",
    "KAYSE.IS": "Kayse",
    "KONTR.IS": "Kontrol",
    "KORFM.IS": "Korfm",
    "LKMNH.IS": "Lokman",
    "MAKIM.IS": "Makim",
    "MGROS.IS": "Migros",
    "MRGYO.IS": "Merit Gayrimenkul",
    "ODAS.IS": "Odas",
    "PNLSN.IS": "Pınar",
    "PSDTC.IS": "Panda",
    "SEKFK.IS": "Şeker",
    "SEKFS.IS": "Şeker Finans",
    "SOKM.IS": "ŞOK Marketler",
}

SECTOR_MAP = {
    "THYAO.IS": "HAVA",
    "ASELS.IS": "TEKNO",
    "SASA.IS": "KIMYA",
    "KCHOL.IS": "HOLDI",
    "EREGL.IS": "KIMYA",
    "BIMAS.IS": "PERAK",
    "TUPRS.IS": "KIMYA",
    "SAHOL.IS": "HOLDI",
    "GARAN.IS": "FINANS",
    "AKBNK.IS": "FINANS",
}


@dataclass(frozen=True)
class Settings:
    DEFAULT_BIST100_WATCHLIST: list[str] = field(default_factory=lambda: list(DEFAULT_BIST100_WATCHLIST))
    WATCHLIST: list[str] = field(default_factory=lambda: list(DEFAULT_BIST100_WATCHLIST))
    TICKER_NAMES: dict[str, str] = field(default_factory=lambda: dict(TICKER_NAMES))
    SECTOR_MAP: dict[str, str] = field(default_factory=lambda: dict(SECTOR_MAP))

    TELEGRAM_BOT_TOKEN: str = _get_str_env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = _get_str_env("TELEGRAM_CHAT_ID")
    DB_PATH: str = _get_str_env("DB_PATH", "bist_signals.db")

    SCAN_INTERVAL_MINUTES: int = _get_int_env("SCAN_INTERVAL_MINUTES", 15)
    MARKET_OPEN_HOUR: int = _get_int_env("MARKET_OPEN_HOUR", 9)
    MARKET_CLOSE_HOUR: int = _get_int_env("MARKET_CLOSE_HOUR", 18)
    MARKET_WARMUP_MINUTES: int = _get_int_env("MARKET_WARMUP_MINUTES", 15)
    MARKET_HALF_DAY_HOUR: int = _get_int_env("MARKET_HALF_DAY_HOUR", 13)

    RSI_PERIOD: int = _get_int_env("RSI_PERIOD", 14)
    RSI_OVERSOLD: int = _get_int_env("RSI_OVERSOLD", 30)
    RSI_OVERBOUGHT: int = _get_int_env("RSI_OVERBOUGHT", 70)
    SMA_FAST: int = _get_int_env("SMA_FAST", 5)
    SMA_SLOW: int = _get_int_env("SMA_SLOW", 20)
    EMA_FAST: int = _get_int_env("EMA_FAST", 12)
    EMA_SLOW: int = _get_int_env("EMA_SLOW", 26)
    EMA_LONG: int = _get_int_env("EMA_LONG", 200)
    MACD_FAST: int = _get_int_env("MACD_FAST", 12)
    MACD_SLOW: int = _get_int_env("MACD_SLOW", 26)
    MACD_SIGNAL: int = _get_int_env("MACD_SIGNAL", 9)
    BOLLINGER_PERIOD: int = _get_int_env("BOLLINGER_PERIOD", 20)
    BOLLINGER_STD: float = _get_float_env("BOLLINGER_STD", 2.0)
    ADX_THRESHOLD: int = _get_int_env("ADX_THRESHOLD", 20)
    VOLUME_CONFIRM_MULTIPLIER: float = _get_float_env("VOLUME_CONFIRM_MULTIPLIER", 1.5)
    VOLUME_SPIKE_MULTIPLIER: float = _get_float_env("VOLUME_SPIKE_MULTIPLIER", 1.5)

    DATA_PERIOD: str = _get_str_env("DATA_PERIOD", "3mo")
    DATA_INTERVAL: str = _get_str_env("DATA_INTERVAL", "1d")
    MTF_ENABLED: bool = _get_bool_env("MTF_ENABLED", True)
    MTF_TREND_PERIOD: str = _get_str_env("MTF_TREND_PERIOD", "6mo")
    MTF_TREND_INTERVAL: str = _get_str_env("MTF_TREND_INTERVAL", "1d")
    MTF_TRIGGER_PERIOD: str = _get_str_env("MTF_TRIGGER_PERIOD", "1mo")
    MTF_TRIGGER_INTERVAL: str = _get_str_env("MTF_TRIGGER_INTERVAL", "15m")

    CORRELATION_THRESHOLD: float = _get_float_env("CORRELATION_THRESHOLD", 0.70)
    CORRELATION_RISK_STEP: float = _get_float_env("CORRELATION_RISK_STEP", 0.35)
    CORRELATION_MIN_SCALE: float = _get_float_env("CORRELATION_MIN_SCALE", 0.25)
    CORRELATION_MAX_CLUSTER: int = _get_int_env("CORRELATION_MAX_CLUSTER", 2)
    ATR_BASELINE_PCT: float = _get_float_env("ATR_BASELINE_PCT", 0.025)
    ATR_MIN_RISK_SCALE: float = _get_float_env("ATR_MIN_RISK_SCALE", 0.35)

    ENABLE_REALTIME_SCRAPING: bool = _get_bool_env("ENABLE_REALTIME_SCRAPING", True)
    RATE_LIMIT_SECONDS: float = _get_float_env("RATE_LIMIT_SECONDS", 2.0)
    NOTIFICATION_MAX_RETRIES: int = _get_int_env("NOTIFICATION_MAX_RETRIES", 3)
    NOTIFICATION_RETRY_DELAY: int = _get_int_env("NOTIFICATION_RETRY_DELAY", 5)

    FLASK_PORT: int = _get_int_env("FLASK_PORT", 5000)
    FLASK_DEBUG: bool = _get_bool_env("FLASK_DEBUG", False)

    INITIAL_CAPITAL: float = _get_float_env("INITIAL_CAPITAL", 8500.0)
    ML_SEQUENCE_LENGTH: int = _get_int_env("ML_SEQUENCE_LENGTH", 60)
    ML_EPOCHS: int = _get_int_env("ML_EPOCHS", 50)
    ML_BATCH_SIZE: int = _get_int_env("ML_BATCH_SIZE", 32)
    ML_MODEL_PATH: str = _get_str_env("ML_MODEL_PATH", "models")

    BENCHMARK_TICKER: str = _get_str_env("BENCHMARK_TICKER", "^XU100")
    BENCHMARK_TICKER_ALT: str = _get_str_env("BENCHMARK_TICKER_ALT", "XRXIST.IS")

    PAPER_MODE: bool = _get_bool_env("PAPER_MODE", False)
    PAPER_TRADES_TABLE: str = _get_str_env("PAPER_TRADES_TABLE", "paper_trades")

    COMMISSION_BUY: float = _get_float_env("COMMISSION_BUY", 0.0002)
    COMMISSION_SELL: float = _get_float_env("COMMISSION_SELL", 0.0002)
    BSMV: float = _get_float_env("BSMV", 0.0005)
    SLIPPAGE: float = _get_float_env("SLIPPAGE", 0.001)
    BACKTEST_COMMISSION_PCT: float = _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    BACKTEST_COMMISSION_BUY_PCT: float = _get_float_env("BACKTEST_COMMISSION_BUY_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001))
    BACKTEST_COMMISSION_SELL_PCT: float = _get_float_env("BACKTEST_COMMISSION_SELL_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001))
    BACKTEST_SLIPPAGE_PCT: float = _get_float_env("BACKTEST_SLIPPAGE_PCT", 0.0005)

    TELEGRAM_MIN_SCORE: int = _get_int_env("TELEGRAM_MIN_SCORE", 70)

    STRONG_BUY_THRESHOLD: int = _get_int_env("STRONG_BUY_THRESHOLD", 48)
    BUY_THRESHOLD: int = _get_int_env("BUY_THRESHOLD", 20)
    WEAK_BUY_THRESHOLD: int = _get_int_env("WEAK_BUY_THRESHOLD", 8)
    WEAK_SELL_THRESHOLD: int = _get_int_env("WEAK_SELL_THRESHOLD", -8)
    SELL_THRESHOLD: int = _get_int_env("SELL_THRESHOLD", -20)
    STRONG_SELL_THRESHOLD: int = _get_int_env("STRONG_SELL_THRESHOLD", -48)

    WALKFORWARD_TRAIN_DAYS: int = _get_int_env("WALKFORWARD_TRAIN_DAYS", 180)
    WALKFORWARD_TEST_DAYS: int = _get_int_env("WALKFORWARD_TEST_DAYS", 30)
    SECTOR_LIMIT: int = _get_int_env("SECTOR_LIMIT", 2)

    def _load_persisted_settings(self) -> dict[str, Any]:
        """Load persisted settings from JSON file."""
        if not CONFIG_FILE.exists():
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure all sections exist with defaults
            for section, defaults in self.DEFAULT_SETTINGS.items():
                if section not in data:
                    data[section] = defaults.copy()
                else:
                    for key, value in defaults.items():
                        if key not in data[section]:
                            data[section][key] = value
            return data
        except Exception as e:
            logger.warning(f"Settings load failed: {e}, using defaults")
            return {}

    def _apply_indicator_overrides(self, data: dict[str, Any]) -> None:
        """Apply indicator settings from persisted data."""
        indicator_data = data.get("indicator", {})
        # Note: Since Settings is frozen, we can't actually override these.
        # The overrides are handled in session_state.py instead.
        pass

    def _apply_telegram_overrides(self, data: dict[str, Any]) -> None:
        """Apply telegram settings from persisted data."""
        telegram_data = data.get("telegram", {})
        # Note: Since Settings is frozen, we can't actually override these.
        # The overrides are handled in session_state.py instead.
        pass

    def _apply_scan_overrides(self, data: dict[str, Any]) -> None:
        """Apply scan settings from persisted data."""
        scan_data = data.get("scan", {})
        # Note: Since Settings is frozen, we can't actually override these.
        # The overrides are handled in session_state.py instead.
        pass

    def save_settings(self, user_settings: dict[str, Any]) -> bool:
        """Save settings to JSON file, preserving sensitive fields as empty."""
        try:
            # Create a copy to avoid modifying the original
            settings_to_save = json.loads(json.dumps(user_settings))
            # Clear sensitive fields for security
            telegram = settings_to_save.setdefault("telegram", {})
            telegram["bot_token"] = ""
            telegram["chat_id"] = ""
            
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(settings_to_save, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Settings save failed: {e}")
            return False

    def reset_settings(self) -> bool:
        """Reset settings to defaults by deleting the JSON file."""
        try:
            if CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
            return True
        except Exception as e:
            logger.error(f"Settings reset failed: {e}")
            return False

    @classmethod
    def get_indicator_defaults(cls) -> dict:
        return cls.DEFAULT_SETTINGS["indicator"].copy()

    @classmethod
    def get_telegram_settings(cls) -> dict:
        return cls.DEFAULT_SETTINGS["telegram"].copy()

    @classmethod
    def get_scan_settings(cls) -> dict:
        return cls.DEFAULT_SETTINGS["scan"].copy()


settings = Settings()
