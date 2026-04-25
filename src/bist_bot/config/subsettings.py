"""Composable sub-settings groups for the main Settings facade."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from bist_bot.data.bist100 import BIST100_TICKERS


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
        file_path = os.getenv(f"{name}_FILE")
        if not file_path:
            return default
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return default
    return value.strip()


def _get_csv_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return ()
    items = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(items)


DEFAULT_FLASK_PORT = _get_int_env("PORT", _get_int_env("FLASK_PORT", 5000))

DEFAULT_BIST100_WATCHLIST = BIST100_TICKERS

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
    "FMIZP.IS": "Federal-Mogul Izmit Piston",
    "FORMT.IS": "Formet",
    "GENTS.IS": "Gentas",
    "GLYHO.IS": "Gülho",
    "IPEKE.IS": "İpek",
    "IZMDC.IS": "İzdemir",
    "KARSN.IS": "Karsan",
    "KAYSE.IS": "Kayseri Seker",
    "KONTR.IS": "Kontrol",
    "KORFM.IS": "Korfm",
    "LKMNH.IS": "Lokman",
    "MAKIM.IS": "Makim",
    "MGROS.IS": "Migros",
    "MRGYO.IS": "Merit Gayrimenkul",
    "ODAS.IS": "Odas",
    "PNLSN.IS": "Pınar",
    "PSDTC.IS": "Pasifik Donanim",
    "SEKFK.IS": "Şeker",
    "SEKFS.IS": "Şeker Finans",
    "SOKM.IS": "ŞOK Marketler",
}

SECTOR_MAP = {
    "THYAO.IS": "HAVACILIK",
    "PGSUS.IS": "HAVACILIK",
    "TAVHL.IS": "HAVACILIK",
    "ASELS.IS": "SAVUNMA",
    "SASA.IS": "KİMYA",
    "PETKM.IS": "KİMYA",
    "KCHOL.IS": "HOLDİNG",
    "SAHOL.IS": "HOLDİNG",
    "EREGL.IS": "DEMİR-ÇELİK",
    "KRDMD.IS": "DEMİR-ÇELİK",
    "BIMAS.IS": "PERAKENDE",
    "MGROS.IS": "PERAKENDE",
    "SOKM.IS": "PERAKENDE",
    "TUPRS.IS": "ENERJİ",
    "AYGAZ.IS": "ENERJİ",
    "ENJSA.IS": "ENERJİ",
    "ODAS.IS": "ENERJİ",
    "GWIND.IS": "ENERJİ",
    "GARAN.IS": "BANKA",
    "AKBNK.IS": "BANKA",
    "ISCTR.IS": "BANKA",
    "YKBNK.IS": "BANKA",
    "HALKB.IS": "BANKA",
    "VAKBN.IS": "BANKA",
    "TOASO.IS": "OTOMOTİV",
    "FROTO.IS": "OTOMOTİV",
    "DOAS.IS": "OTOMOTİV",
    "ARCLK.IS": "DAYANIKLI",
    "VESBE.IS": "DAYANIKLI",
    "CCOLA.IS": "GIDA",
    "AEFES.IS": "GIDA",
    "ULKER.IS": "GIDA",
    "SISE.IS": "CAM",
    "HEKTS.IS": "TARIM",
    "CIMSA.IS": "ÇİMENTO",
    "AKCNS.IS": "ÇİMENTO",
    "OYAKC.IS": "ÇİMENTO",
    "ENKAI.IS": "İNŞAAT",
    "TKFEN.IS": "İNŞAAT",
    "TCELL.IS": "TELEKOM",
    "TTKOM.IS": "TELEKOM",
    "KOZAL.IS": "MADENCİLİK",
    "KOZAA.IS": "MADENCİLİK",
    "ISGYO.IS": "GYO",
    "EKGYO.IS": "GYO",
}


@dataclass(frozen=True)
class TradingSettings:
    STRONG_BUY_THRESHOLD: int = _get_int_env("STRONG_BUY_THRESHOLD", 48)
    BUY_THRESHOLD: int = _get_int_env("BUY_THRESHOLD", 20)
    WEAK_BUY_THRESHOLD: int = _get_int_env("WEAK_BUY_THRESHOLD", 8)
    WEAK_SELL_THRESHOLD: int = _get_int_env("WEAK_SELL_THRESHOLD", -8)
    SELL_THRESHOLD: int = _get_int_env("SELL_THRESHOLD", -20)
    STRONG_SELL_THRESHOLD: int = _get_int_env("STRONG_SELL_THRESHOLD", -48)
    SIDEWAYS_EXTRA_THRESHOLD: float = _get_float_env("SIDEWAYS_EXTRA_THRESHOLD", 5.0)
    MOMENTUM_CONFIRMATION_THRESHOLD: float = _get_float_env(
        "MOMENTUM_CONFIRMATION_THRESHOLD", 4.0
    )
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
    VOLUME_CONFIRM_TICKER_OVERRIDES: dict[str, float] = field(
        default_factory=lambda: {
            "SASA.IS": 1.2,
            "EREGL.IS": 1.2,
            "KRDMD.IS": 1.2,
            "THYAO.IS": 1.8,
            "GARAN.IS": 1.8,
            "AKBNK.IS": 1.8,
        }
    )
    WALKFORWARD_TRAIN_DAYS: int = _get_int_env("WALKFORWARD_TRAIN_DAYS", 180)
    WALKFORWARD_TEST_DAYS: int = _get_int_env("WALKFORWARD_TEST_DAYS", 30)
    SECTOR_LIMIT: int = _get_int_env("SECTOR_LIMIT", 2)
    INITIAL_CAPITAL: float = _get_float_env("INITIAL_CAPITAL", 100000.0)
    PAPER_MODE: bool = _get_bool_env("PAPER_MODE", False)
    PAPER_TRADES_TABLE: str = _get_str_env("PAPER_TRADES_TABLE", "paper_trades")
    COMMISSION_BUY: float = _get_float_env("COMMISSION_BUY", 0.0002)
    COMMISSION_SELL: float = _get_float_env("COMMISSION_SELL", 0.0002)
    BSMV: float = _get_float_env("BSMV", 0.0005)
    SLIPPAGE: float = _get_float_env("SLIPPAGE", 0.001)
    SLIPPAGE_PCT: float = _get_float_env("SLIPPAGE_PCT", 0.001)
    SLIPPAGE_PENALTY_RATIO: float = _get_float_env("SLIPPAGE_PENALTY_RATIO", 0.15)
    SLIPPAGE_MAX_CAP: float = _get_float_env("SLIPPAGE_MAX_CAP", 0.02)


@dataclass(frozen=True)
class RiskSettings:
    CORRELATION_THRESHOLD: float = _get_float_env("CORRELATION_THRESHOLD", 0.70)
    CORRELATION_RISK_STEP: float = _get_float_env("CORRELATION_RISK_STEP", 0.35)
    CORRELATION_MIN_SCALE: float = _get_float_env("CORRELATION_MIN_SCALE", 0.25)
    CORRELATION_MAX_CLUSTER: int = _get_int_env("CORRELATION_MAX_CLUSTER", 2)
    ATR_BASELINE_PCT: float = _get_float_env("ATR_BASELINE_PCT", 0.025)
    ATR_MIN_RISK_SCALE: float = _get_float_env("ATR_MIN_RISK_SCALE", 0.35)
    MAX_POSITION_CAP_PCT: float = _get_float_env("MAX_POSITION_CAP_PCT", 5.0)
    MAX_SECTOR_CAP_PCT: float = _get_float_env("MAX_SECTOR_CAP_PCT", 20.0)
    MAX_TOTAL_RISK_PCT: float = _get_float_env("MAX_TOTAL_RISK_PCT", 2.0)
    KELLY_FRACTION_SCALE: float = _get_float_env("KELLY_FRACTION_SCALE", 0.25)
    MIN_SIGNAL_PROBABILITY: float = _get_float_env("MIN_SIGNAL_PROBABILITY", 0.50)
    MIN_LIQUIDITY_VALUE_TL: float = _get_float_env("MIN_LIQUIDITY_VALUE_TL", 0.0)
    DAILY_LOSS_CAP_PCT: float = _get_float_env("DAILY_LOSS_CAP_PCT", 3.0)


@dataclass(frozen=True)
class DataSettings:
    DATA_PERIOD: str = _get_str_env("DATA_PERIOD", "3mo")
    DATA_INTERVAL: str = _get_str_env("DATA_INTERVAL", "1d")
    DATA_PROVIDER: str = _get_str_env("DATA_PROVIDER", "yfinance").lower()
    MTF_ENABLED: bool = _get_bool_env("MTF_ENABLED", True)
    MTF_TREND_PERIOD: str = _get_str_env("MTF_TREND_PERIOD", "6mo")
    MTF_TREND_INTERVAL: str = _get_str_env("MTF_TREND_INTERVAL", "1d")
    MTF_TRIGGER_PERIOD: str = _get_str_env("MTF_TRIGGER_PERIOD", "1mo")
    MTF_TRIGGER_INTERVAL: str = _get_str_env("MTF_TRIGGER_INTERVAL", "15m")
    ENABLE_REALTIME_SCRAPING: bool = _get_bool_env("ENABLE_REALTIME_SCRAPING", True)
    RATE_LIMIT_SECONDS: float = _get_float_env("RATE_LIMIT_SECONDS", 2.0)
    FETCH_CACHE_TTL_SECONDS: float = _get_float_env("FETCH_CACHE_TTL_SECONDS", 900.0)
    INTRADAY_FETCH_CACHE_TTL_SECONDS: float = _get_float_env(
        "INTRADAY_FETCH_CACHE_TTL_SECONDS", 120.0
    )
    ANALYSIS_CACHE_TTL_SECONDS: float = _get_float_env(
        "ANALYSIS_CACHE_TTL_SECONDS", 180.0
    )
    REALTIME_QUOTE_CACHE_TTL_SECONDS: float = _get_float_env(
        "REALTIME_QUOTE_CACHE_TTL_SECONDS", 30.0
    )
    OFFICIAL_VENDOR: str = _get_str_env("OFFICIAL_VENDOR", "generic").lower()
    OFFICIAL_API_BASE_URL: str = _get_str_env("OFFICIAL_API_BASE_URL")
    OFFICIAL_API_KEY: str = _get_str_env("OFFICIAL_API_KEY")
    OFFICIAL_USERNAME: str = _get_str_env("OFFICIAL_USERNAME")
    OFFICIAL_PASSWORD: str = _get_str_env("OFFICIAL_PASSWORD")
    OFFICIAL_TIMEOUT: float = _get_float_env("OFFICIAL_TIMEOUT", 30.0)
    OFFICIAL_MAX_RETRIES: int = _get_int_env("OFFICIAL_MAX_RETRIES", 3)
    OFFICIAL_RETRY_BACKOFF_SECONDS: float = _get_float_env(
        "OFFICIAL_RETRY_BACKOFF_SECONDS", 1.0
    )
    OFFICIAL_AUTH_ENDPOINT: str = _get_str_env("OFFICIAL_AUTH_ENDPOINT")
    OFFICIAL_HISTORY_ENDPOINT: str = _get_str_env("OFFICIAL_HISTORY_ENDPOINT")
    OFFICIAL_BATCH_ENDPOINT: str = _get_str_env("OFFICIAL_BATCH_ENDPOINT")
    OFFICIAL_QUOTE_ENDPOINT: str = _get_str_env("OFFICIAL_QUOTE_ENDPOINT")
    OFFICIAL_UNIVERSE_ENDPOINT: str = _get_str_env("OFFICIAL_UNIVERSE_ENDPOINT")
    BENCHMARK_TICKER: str = _get_str_env("BENCHMARK_TICKER", "^XU100")
    BENCHMARK_TICKER_ALT: str = _get_str_env("BENCHMARK_TICKER_ALT", "XRXIST.IS")


@dataclass(frozen=True)
class DatabaseSettings:
    DATABASE_URL: str = _get_str_env("DATABASE_URL")
    DB_PATH: str = _get_str_env("DB_PATH", "/tmp/bist_signals.db")


@dataclass(frozen=True)
class AuthSettings:
    JWT_SECRET_KEY: str = _get_str_env("JWT_SECRET_KEY")
    ADMIN_BOOTSTRAP_EMAIL: str = _get_str_env("ADMIN_BOOTSTRAP_EMAIL")
    ADMIN_BOOTSTRAP_PASSWORD_HASH: str = _get_str_env("ADMIN_BOOTSTRAP_PASSWORD_HASH")
    ALLOW_PUBLIC_REGISTRATION: bool = _get_bool_env("ALLOW_PUBLIC_REGISTRATION", False)
    CORS_ORIGINS: tuple[str, ...] = field(
        default_factory=lambda: _get_csv_env("CORS_ORIGINS")
    )


@dataclass(frozen=True)
class ServerSettings:
    FLASK_PORT: int = DEFAULT_FLASK_PORT
    FLASK_DEBUG: bool = _get_bool_env("FLASK_DEBUG", False)
    LOG_FORMAT: str = _get_str_env("LOG_FORMAT", "console")
    LOG_LEVEL: str = _get_str_env("LOG_LEVEL", "INFO")
    API_BASE_URL: str = _get_str_env(
        "API_BASE_URL", f"http://localhost:{DEFAULT_FLASK_PORT}"
    )
    RATE_LIMIT_STORAGE_URI: str = _get_str_env("RATE_LIMIT_STORAGE_URI", "memory://")
    SENTRY_DSN: str | None = _get_str_env("SENTRY_DSN") or None
    ENVIRONMENT: str = _get_str_env("ENVIRONMENT", "production")
    STREAMLIT_SCAN_COOLDOWN_SECONDS: float = _get_float_env(
        "STREAMLIT_SCAN_COOLDOWN_SECONDS", 8.0
    )
    STREAMLIT_ANALYZE_COOLDOWN_SECONDS: float = _get_float_env(
        "STREAMLIT_ANALYZE_COOLDOWN_SECONDS", 4.0
    )
    SCAN_INTERVAL_MINUTES: int = _get_int_env("SCAN_INTERVAL_MINUTES", 15)
    MARKET_OPEN_HOUR: int = _get_int_env("MARKET_OPEN_HOUR", 9)
    MARKET_CLOSE_HOUR: int = _get_int_env("MARKET_CLOSE_HOUR", 18)
    MARKET_WARMUP_MINUTES: int = _get_int_env("MARKET_WARMUP_MINUTES", 15)
    MARKET_HALF_DAY_HOUR: int = _get_int_env("MARKET_HALF_DAY_HOUR", 13)


@dataclass(frozen=True)
class BrokerSettings:
    BROKER_PROVIDER: str = _get_str_env("BROKER_PROVIDER", "paper").lower()
    ALGOLAB_API_KEY: str = _get_str_env("ALGOLAB_API_KEY")
    ALGOLAB_USERNAME: str = _get_str_env("ALGOLAB_USERNAME")
    ALGOLAB_PASSWORD: str = _get_str_env("ALGOLAB_PASSWORD")
    ALGOLAB_OTP_CODE: str = _get_str_env("ALGOLAB_OTP_CODE")
    ALGOLAB_DRY_RUN: bool = _get_bool_env("ALGOLAB_DRY_RUN", True)
    AUTO_EXECUTE: bool = _get_bool_env("AUTO_EXECUTE", False)
    CONFIRM_LIVE_TRADING: bool = _get_bool_env("CONFIRM_LIVE_TRADING", False)
    AUTO_EXECUTE_WARN_MAX_QUANTITY: int = _get_int_env(
        "AUTO_EXECUTE_WARN_MAX_QUANTITY", 100000
    )


@dataclass(frozen=True)
class BacktestSettings:
    BACKTEST_COMMISSION_PCT: float = _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    BACKTEST_COMMISSION_BUY_PCT: float = _get_float_env(
        "BACKTEST_COMMISSION_BUY_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    )
    BACKTEST_COMMISSION_SELL_PCT: float = _get_float_env(
        "BACKTEST_COMMISSION_SELL_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    )
    BACKTEST_SLIPPAGE_PCT: float = _get_float_env("BACKTEST_SLIPPAGE_PCT", 0.0005)


@dataclass(frozen=True)
class MLSettings:
    ML_SEQUENCE_LENGTH: int = _get_int_env("ML_SEQUENCE_LENGTH", 60)
    ML_EPOCHS: int = _get_int_env("ML_EPOCHS", 50)
    ML_BATCH_SIZE: int = _get_int_env("ML_BATCH_SIZE", 32)
    ML_MODEL_PATH: str = _get_str_env("ML_MODEL_PATH", "models")


@dataclass(frozen=True)
class NotificationSettings:
    TELEGRAM_BOT_TOKEN: str = _get_str_env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = _get_str_env("TELEGRAM_CHAT_ID")
    TELEGRAM_MIN_SCORE: int = _get_int_env(
        "TELEGRAM_MIN_SCORE", _get_int_env("STRONG_BUY_THRESHOLD", 48)
    )
    NOTIFICATION_MAX_RETRIES: int = _get_int_env("NOTIFICATION_MAX_RETRIES", 3)
    NOTIFICATION_RETRY_DELAY: int = _get_int_env("NOTIFICATION_RETRY_DELAY", 5)
