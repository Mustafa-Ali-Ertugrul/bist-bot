"""Runtime application settings loaded from environment variables."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from bist_bot.data.bist100 import BIST100_TICKERS

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


_SETTINGS_OVERRIDES: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "settings_overrides",
    default=(),
)


class SettingsOverride:
    def __init__(self, settings_obj: Settings, **overrides: Any) -> None:
        valid_fields = settings_obj.__dataclass_fields__
        unknown_fields = sorted(name for name in overrides if name not in valid_fields)
        if unknown_fields:
            unknown = ", ".join(unknown_fields)
            raise AttributeError(f"Unknown settings override(s): {unknown}")
        self._overrides = overrides
        self._token: Token[tuple[dict[str, Any], ...]] | None = None

    def __enter__(self) -> Settings:
        current = _SETTINGS_OVERRIDES.get()
        self._token = _SETTINGS_OVERRIDES.set((*current, self._overrides))
        return settings

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._token is not None:
            _SETTINGS_OVERRIDES.reset(self._token)
            self._token = None


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


def _get_csv_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return ()
    items = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(items)


DEFAULT_BIST100_WATCHLIST = BIST100_TICKERS

TICKER_NAMES = {
    # Bankacilik & Finans
    "AKBNK.IS": "Akbank",
    "GARAN.IS": "Garanti BBVA",
    "HALKB.IS": "Halkbank",
    "ISCTR.IS": "İş Bankası",
    "VAKBN.IS": "VakıfBank",
    "YKBNK.IS": "Yapı Kredi",
    "ALBRK.IS": "Albaraka Türk",
    "QNBFB.IS": "QNB Finansbank",
    "SKBNK.IS": "Şekerbank",
    "TSKB.IS": "Türkiye Sınai Kalkınma Bankası",
    # Holding
    "KCHOL.IS": "Koç Holding",
    "SAHOL.IS": "Sabancı Holding",
    "DOHOL.IS": "Doğan Holding",
    "GLYHO.IS": "Global Yatırım Holding",
    "GSDHO.IS": "GSD Holding",
    "ALARK.IS": "Alarko Holding",
    "ECILC.IS": "Eczacıbaşı İlaç",
    "YGGYO.IS": "Yeni Gimat GYO",
    # Havayolu & Ulastirma
    "THYAO.IS": "Türk Hava Yolları",
    "PGSUS.IS": "Pegasus Hava Yolları",
    "TAVHL.IS": "TAV Havalimanları",
    "CLEBI.IS": "Çelebi Hava Servisi",
    "DOCO.IS": "DO & CO",
    # Otomotiv
    "FROTO.IS": "Ford Otosan",
    "TOASO.IS": "Tofaş Oto",
    "TTRAK.IS": "Türk Traktör",
    "OTKAR.IS": "Otokar",
    "DOAS.IS": "Doğuş Otomotiv",
    "KARSN.IS": "Karsan Otomotiv",
    # Demir-Celik & Metal
    "EREGL.IS": "Ereğli Demir Çelik",
    "KRDMD.IS": "Kardemir (D)",
    "BRSAN.IS": "Borusan Boru",
    "CEMTS.IS": "Çemtaş",
    "IZMDC.IS": "İzmir Demir Çelik",
    # Kimya & Petrokimya & Rafineri
    "TUPRS.IS": "Tüpraş",
    "PETKM.IS": "Petkim",
    "SASA.IS": "SASA Polyester",
    "AKSA.IS": "Aksa Akrilik",
    "ALKIM.IS": "Alkim Kimya",
    "GUBRF.IS": "Gübre Fabrikaları",
    "BAGFS.IS": "Bagfaş",
    "HEKTS.IS": "Hektaş",
    # Cimento & Insaat
    "CIMSA.IS": "Çimsa",
    "AKCNS.IS": "Akçansa",
    "OYAKC.IS": "OYAK Çimento",
    "BTCIM.IS": "Batıçim",
    "ENKAI.IS": "Enka İnşaat",
    "TKFEN.IS": "Tekfen Holding",
    # Cam
    "SISE.IS": "Şişecam",
    "ANACM.IS": "Anadolu Cam",
    # Beyaz Esya & Dayanikli Tuketim
    "ARCLK.IS": "Arçelik",
    "VESTL.IS": "Vestel",
    "VESBE.IS": "Vestel Beyaz Eşya",
    # Gida & Icecek & Perakende
    "BIMAS.IS": "BİM Birleşik Mağazalar",
    "MGROS.IS": "Migros",
    "SOKM.IS": "ŞOK Marketler",
    "AEFES.IS": "Anadolu Efes",
    "CCOLA.IS": "Coca-Cola İçecek",
    "ULKER.IS": "Ülker Bisküvi",
    "TUKAS.IS": "Tukaş",
    "PNSUT.IS": "Pınar Süt",
    # Enerji & Elektrik
    "ENJSA.IS": "Enerjisa Enerji",
    "AKSEN.IS": "Aksa Enerji",
    "AYGAZ.IS": "Aygaz",
    "ZOREN.IS": "Zorlu Enerji",
    "ODAS.IS": "Odaş Elektrik",
    "AYDEM.IS": "Aydem Yenilenebilir Enerji",
    "CWENE.IS": "CW Enerji",
    "SMRTG.IS": "Smart Güneş Enerjisi",
    "EUPWR.IS": "Europower Enerji",
    # Teknoloji & Savunma
    "ASELS.IS": "ASELSAN",
    "LOGO.IS": "Logo Yazılım",
    "KAREL.IS": "Karel Elektronik",
    "NETAS.IS": "Netaş Telekom.",
    "INDES.IS": "İndeks Bilgisayar",
    "ARENA.IS": "Arena Bilgisayar",
    "FONET.IS": "Fonet Bilgi Teknolojileri",
    "MIATK.IS": "MIA Teknoloji",
    "KONTR.IS": "Kontrolmatik Teknoloji",
    "GESAN.IS": "Girişim Elektrik",
    "PAPIL.IS": "Papilon Savunma",
    # Iletisim
    "TCELL.IS": "Turkcell",
    "TTKOM.IS": "Türk Telekom",
    # Madencilik
    "KOZAL.IS": "Koza Altın",
    "KOZAA.IS": "Koza Anadolu Metal",
    "IPEKE.IS": "İpek Doğal Enerji",
    # Lastik
    "BRISA.IS": "Brisa",
    # Tekstil & Hazir Giyim
    "MAVI.IS": "Mavi Giyim",
    "DESA.IS": "Desa Deri",
    # Ilac & Saglik
    "DEVA.IS": "Deva Holding",
    "LKMNH.IS": "Lokman Hekim Sağlık",
    "MPARK.IS": "MLP Sağlık (Medical Park)",
    "SELEC.IS": "Selçuk Ecza Deposu",
    # Gayrimenkul
    "EKGYO.IS": "Emlak Konut GYO",
    "ISGYO.IS": "İş GYO",
    "AKMGY.IS": "Akmerkez GYO",
    "TRGYO.IS": "Torunlar GYO",
    # Spor
    "FENER.IS": "Fenerbahçe Sportif",
    "BJKAS.IS": "Beşiktaş",
    "GSRAY.IS": "Galatasaray Sportif",
}

SECTOR_MAP = {
    # Bankacilik & Finans
    "AKBNK.IS": "BANKA",
    "GARAN.IS": "BANKA",
    "HALKB.IS": "BANKA",
    "ISCTR.IS": "BANKA",
    "VAKBN.IS": "BANKA",
    "YKBNK.IS": "BANKA",
    "ALBRK.IS": "BANKA",
    "QNBFB.IS": "BANKA",
    "SKBNK.IS": "BANKA",
    "TSKB.IS": "BANKA",
    # Holding
    "KCHOL.IS": "HOLDI",
    "SAHOL.IS": "HOLDI",
    "DOHOL.IS": "HOLDI",
    "GLYHO.IS": "HOLDI",
    "GSDHO.IS": "HOLDI",
    "ALARK.IS": "HOLDI",
    "ECILC.IS": "HOLDI",
    # Ulastirma & Havayolu
    "THYAO.IS": "ULASTIRMA",
    "PGSUS.IS": "ULASTIRMA",
    "TAVHL.IS": "ULASTIRMA",
    "CLEBI.IS": "ULASTIRMA",
    "DOCO.IS": "ULASTIRMA",
    # Otomotiv
    "FROTO.IS": "OTOMOTIV",
    "TOASO.IS": "OTOMOTIV",
    "TTRAK.IS": "OTOMOTIV",
    "OTKAR.IS": "OTOMOTIV",
    "DOAS.IS": "OTOMOTIV",
    "KARSN.IS": "OTOMOTIV",
    # Metal
    "EREGL.IS": "METAL",
    "KRDMD.IS": "METAL",
    "BRSAN.IS": "METAL",
    "CEMTS.IS": "METAL",
    "IZMDC.IS": "METAL",
    # Kimya
    "TUPRS.IS": "KIMYA",
    "PETKM.IS": "KIMYA",
    "SASA.IS": "KIMYA",
    "AKSA.IS": "KIMYA",
    "ALKIM.IS": "KIMYA",
    "GUBRF.IS": "KIMYA",
    "BAGFS.IS": "KIMYA",
    "HEKTS.IS": "KIMYA",
    # Insaat & Cimento
    "CIMSA.IS": "INSAAT",
    "AKCNS.IS": "INSAAT",
    "OYAKC.IS": "INSAAT",
    "BTCIM.IS": "INSAAT",
    "ENKAI.IS": "INSAAT",
    "TKFEN.IS": "INSAAT",
    # Cam
    "SISE.IS": "CAM",
    "ANACM.IS": "CAM",
    # Beyaz Esya
    "ARCLK.IS": "DAYANIKLI",
    "VESTL.IS": "DAYANIKLI",
    "VESBE.IS": "DAYANIKLI",
    # Gida & Perakende
    "BIMAS.IS": "PERAK",
    "MGROS.IS": "PERAK",
    "SOKM.IS": "PERAK",
    "AEFES.IS": "GIDA",
    "CCOLA.IS": "GIDA",
    "ULKER.IS": "GIDA",
    "TUKAS.IS": "GIDA",
    "PNSUT.IS": "GIDA",
    # Enerji
    "ENJSA.IS": "ENERJI",
    "AKSEN.IS": "ENERJI",
    "AYGAZ.IS": "ENERJI",
    "ZOREN.IS": "ENERJI",
    "ODAS.IS": "ENERJI",
    "AYDEM.IS": "ENERJI",
    "CWENE.IS": "ENERJI",
    "SMRTG.IS": "ENERJI",
    "EUPWR.IS": "ENERJI",
    # Teknoloji & Savunma
    "ASELS.IS": "TEKNO",
    "LOGO.IS": "TEKNO",
    "KAREL.IS": "TEKNO",
    "NETAS.IS": "TEKNO",
    "INDES.IS": "TEKNO",
    "ARENA.IS": "TEKNO",
    "FONET.IS": "TEKNO",
    "MIATK.IS": "TEKNO",
    "KONTR.IS": "TEKNO",
    "GESAN.IS": "TEKNO",
    "PAPIL.IS": "TEKNO",
    # Iletisim
    "TCELL.IS": "ILETISIM",
    "TTKOM.IS": "ILETISIM",
    # Madencilik
    "KOZAL.IS": "MADEN",
    "KOZAA.IS": "MADEN",
    "IPEKE.IS": "MADEN",
    # Lastik & Tekstil
    "BRISA.IS": "DAYANIKLI",
    "MAVI.IS": "TEKSTIL",
    "DESA.IS": "TEKSTIL",
    # Saglik
    "DEVA.IS": "SAGLIK",
    "LKMNH.IS": "SAGLIK",
    "MPARK.IS": "SAGLIK",
    "SELEC.IS": "SAGLIK",
    # GYO
    "EKGYO.IS": "GAYRIMENKUL",
    "ISGYO.IS": "GAYRIMENKUL",
    "AKMGY.IS": "GAYRIMENKUL",
    "TRGYO.IS": "GAYRIMENKUL",
    "YGGYO.IS": "GAYRIMENKUL",
    # Spor
    "FENER.IS": "SPOR",
    "BJKAS.IS": "SPOR",
    "GSRAY.IS": "SPOR",
}


@dataclass(frozen=True)
class Settings:
    DEFAULT_BIST100_WATCHLIST: list[str] = field(
        default_factory=lambda: list(DEFAULT_BIST100_WATCHLIST)
    )
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
    DATA_PROVIDER: str = _get_str_env("DATA_PROVIDER", "yfinance").lower()
    OFFICIAL_VENDOR: str = _get_str_env("OFFICIAL_VENDOR", "generic").lower()
    OFFICIAL_API_BASE_URL: str = _get_str_env("OFFICIAL_API_BASE_URL")
    OFFICIAL_API_KEY: str = _get_str_env("OFFICIAL_API_KEY")
    OFFICIAL_USERNAME: str = _get_str_env("OFFICIAL_USERNAME")
    OFFICIAL_PASSWORD: str = _get_str_env("OFFICIAL_PASSWORD")
    OFFICIAL_TIMEOUT: float = _get_float_env("OFFICIAL_TIMEOUT", 30.0)
    OFFICIAL_MAX_RETRIES: int = _get_int_env("OFFICIAL_MAX_RETRIES", 3)
    OFFICIAL_RETRY_BACKOFF_SECONDS: float = _get_float_env("OFFICIAL_RETRY_BACKOFF_SECONDS", 1.0)
    OFFICIAL_AUTH_ENDPOINT: str = _get_str_env("OFFICIAL_AUTH_ENDPOINT")
    OFFICIAL_HISTORY_ENDPOINT: str = _get_str_env("OFFICIAL_HISTORY_ENDPOINT")
    OFFICIAL_BATCH_ENDPOINT: str = _get_str_env("OFFICIAL_BATCH_ENDPOINT")
    OFFICIAL_QUOTE_ENDPOINT: str = _get_str_env("OFFICIAL_QUOTE_ENDPOINT")
    OFFICIAL_UNIVERSE_ENDPOINT: str = _get_str_env("OFFICIAL_UNIVERSE_ENDPOINT")
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
    MAX_POSITION_CAP_PCT: float = _get_float_env("MAX_POSITION_CAP_PCT", 90.0)
    KELLY_FRACTION_SCALE: float = _get_float_env("KELLY_FRACTION_SCALE", 0.25)
    MIN_SIGNAL_PROBABILITY: float = _get_float_env("MIN_SIGNAL_PROBABILITY", 0.50)
    MIN_LIQUIDITY_VALUE_TL: float = _get_float_env("MIN_LIQUIDITY_VALUE_TL", 0.0)
    DAILY_LOSS_CAP_PCT: float = _get_float_env("DAILY_LOSS_CAP_PCT", 0.0)

    ENABLE_REALTIME_SCRAPING: bool = _get_bool_env("ENABLE_REALTIME_SCRAPING", True)
    RATE_LIMIT_SECONDS: float = _get_float_env("RATE_LIMIT_SECONDS", 2.0)
    FETCH_CACHE_TTL_SECONDS: float = _get_float_env("FETCH_CACHE_TTL_SECONDS", 900.0)
    INTRADAY_FETCH_CACHE_TTL_SECONDS: float = _get_float_env(
        "INTRADAY_FETCH_CACHE_TTL_SECONDS", 120.0
    )
    ANALYSIS_CACHE_TTL_SECONDS: float = _get_float_env("ANALYSIS_CACHE_TTL_SECONDS", 180.0)
    REALTIME_QUOTE_CACHE_TTL_SECONDS: float = _get_float_env(
        "REALTIME_QUOTE_CACHE_TTL_SECONDS", 30.0
    )
    NOTIFICATION_MAX_RETRIES: int = _get_int_env("NOTIFICATION_MAX_RETRIES", 3)
    NOTIFICATION_RETRY_DELAY: int = _get_int_env("NOTIFICATION_RETRY_DELAY", 5)

    FLASK_PORT: int = _get_int_env("FLASK_PORT", 5000)
    FLASK_DEBUG: bool = _get_bool_env("FLASK_DEBUG", False)
    LOG_FORMAT: str = _get_str_env("LOG_FORMAT", "console")
    LOG_LEVEL: str = _get_str_env("LOG_LEVEL", "INFO")
    STREAMLIT_SCAN_COOLDOWN_SECONDS: float = _get_float_env("STREAMLIT_SCAN_COOLDOWN_SECONDS", 8.0)
    STREAMLIT_ANALYZE_COOLDOWN_SECONDS: float = _get_float_env(
        "STREAMLIT_ANALYZE_COOLDOWN_SECONDS", 4.0
    )
    API_BASE_URL: str = _get_str_env(
        "API_BASE_URL", f"http://localhost:{_get_int_env('FLASK_PORT', 5000)}"
    )
    RATE_LIMIT_STORAGE_URI: str = _get_str_env("RATE_LIMIT_STORAGE_URI", "memory://")
    JWT_SECRET_KEY: str = _get_str_env("JWT_SECRET_KEY")
    ADMIN_BOOTSTRAP_EMAIL: str = _get_str_env("ADMIN_BOOTSTRAP_EMAIL")
    ADMIN_BOOTSTRAP_PASSWORD_HASH: str = _get_str_env("ADMIN_BOOTSTRAP_PASSWORD_HASH")
    CORS_ORIGINS: tuple[str, ...] = field(default_factory=lambda: _get_csv_env("CORS_ORIGINS"))

    INITIAL_CAPITAL: float = _get_float_env("INITIAL_CAPITAL", 100000.0)
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
    AUTO_EXECUTE: bool = _get_bool_env("AUTO_EXECUTE", False)
    CONFIRM_LIVE_TRADING: bool = _get_bool_env("CONFIRM_LIVE_TRADING", False)
    BROKER_PROVIDER: str = _get_str_env("BROKER_PROVIDER", "paper").lower()
    ALGOLAB_API_KEY: str = _get_str_env("ALGOLAB_API_KEY")
    ALGOLAB_USERNAME: str = _get_str_env("ALGOLAB_USERNAME")
    ALGOLAB_PASSWORD: str = _get_str_env("ALGOLAB_PASSWORD")
    ALGOLAB_OTP_CODE: str = _get_str_env("ALGOLAB_OTP_CODE")
    ALGOLAB_DRY_RUN: bool = _get_bool_env("ALGOLAB_DRY_RUN", True)
    AUTO_EXECUTE_WARN_MAX_QUANTITY: int = _get_int_env("AUTO_EXECUTE_WARN_MAX_QUANTITY", 100000)
    SLIPPAGE: float = _get_float_env("SLIPPAGE", 0.001)
    SLIPPAGE_PCT: float = _get_float_env("SLIPPAGE_PCT", 0.001)
    SLIPPAGE_PENALTY_RATIO: float = _get_float_env("SLIPPAGE_PENALTY_RATIO", 0.15)
    SLIPPAGE_MAX_CAP: float = _get_float_env("SLIPPAGE_MAX_CAP", 0.02)
    BACKTEST_COMMISSION_PCT: float = _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    BACKTEST_COMMISSION_BUY_PCT: float = _get_float_env(
        "BACKTEST_COMMISSION_BUY_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    )
    BACKTEST_COMMISSION_SELL_PCT: float = _get_float_env(
        "BACKTEST_COMMISSION_SELL_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    )
    BACKTEST_SLIPPAGE_PCT: float = _get_float_env("BACKTEST_SLIPPAGE_PCT", 0.0005)

    TELEGRAM_MIN_SCORE: int = _get_int_env("TELEGRAM_MIN_SCORE", 70)

    STRONG_BUY_THRESHOLD: int = _get_int_env("STRONG_BUY_THRESHOLD", 48)
    BUY_THRESHOLD: int = _get_int_env("BUY_THRESHOLD", 20)
    WEAK_BUY_THRESHOLD: int = _get_int_env("WEAK_BUY_THRESHOLD", 8)
    WEAK_SELL_THRESHOLD: int = _get_int_env("WEAK_SELL_THRESHOLD", -8)
    SELL_THRESHOLD: int = _get_int_env("SELL_THRESHOLD", -20)
    STRONG_SELL_THRESHOLD: int = _get_int_env("STRONG_SELL_THRESHOLD", -48)
    SIDEWAYS_EXTRA_THRESHOLD: float = _get_float_env("SIDEWAYS_EXTRA_THRESHOLD", 5.0)
    MOMENTUM_CONFIRMATION_THRESHOLD: float = _get_float_env("MOMENTUM_CONFIRMATION_THRESHOLD", 4.0)

    WALKFORWARD_TRAIN_DAYS: int = _get_int_env("WALKFORWARD_TRAIN_DAYS", 180)
    WALKFORWARD_TEST_DAYS: int = _get_int_env("WALKFORWARD_TEST_DAYS", 30)
    SECTOR_LIMIT: int = _get_int_env("SECTOR_LIMIT", 2)

    def __getattribute__(self, name: str) -> Any:
        if not name.startswith("__"):
            dataclass_fields = object.__getattribute__(self, "__dataclass_fields__")
            if name in dataclass_fields:
                for overrides in reversed(_SETTINGS_OVERRIDES.get()):
                    if name in overrides:
                        return overrides[name]
        return object.__getattribute__(self, name)

    def override(self, **overrides: Any) -> SettingsOverride:
        return SettingsOverride(self, **overrides)

    def require_security_config(self) -> None:
        if not self.JWT_SECRET_KEY:
            raise RuntimeError("Missing required security setting(s): JWT_SECRET_KEY")

    @property
    def admin_bootstrap_enabled(self) -> bool:
        return bool(self.ADMIN_BOOTSTRAP_EMAIL and self.ADMIN_BOOTSTRAP_PASSWORD_HASH)

    def validate_broker_config(self) -> None:
        if self.BROKER_PROVIDER not in {"paper", "algolab"}:
            raise RuntimeError(f"Unsupported BROKER_PROVIDER: {self.BROKER_PROVIDER}")
        if self.BROKER_PROVIDER != "algolab":
            return
        if not self.ALGOLAB_API_KEY or not self.ALGOLAB_USERNAME or not self.ALGOLAB_PASSWORD:
            raise RuntimeError("Missing required AlgoLab credentials for BROKER_PROVIDER=algolab")
        if not self.ALGOLAB_DRY_RUN and not self.CONFIRM_LIVE_TRADING:
            raise RuntimeError("CONFIRM_LIVE_TRADING=true is required when ALGOLAB_DRY_RUN=false")

    def validate_data_provider_config(self) -> None:
        if self.DATA_PROVIDER == "official":
            missing = []
            if not self.OFFICIAL_API_BASE_URL:
                missing.append("OFFICIAL_API_BASE_URL")
            if not self.OFFICIAL_API_KEY:
                missing.append("OFFICIAL_API_KEY")
            if not self.OFFICIAL_USERNAME:
                missing.append("OFFICIAL_USERNAME")
            if not self.OFFICIAL_PASSWORD:
                missing.append("OFFICIAL_PASSWORD")
            if missing:
                raise RuntimeError(
                    f"Missing required settings for DATA_PROVIDER=official: {', '.join(missing)}"
                )


settings = Settings()
