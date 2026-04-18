from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


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


DEFAULT_BIST100_WATCHLIST = [
    "THYAO.IS", "ASELS.IS", "SASA.IS", "KCHOL.IS", "EREGL.IS",
    "BIMAS.IS", "TUPRS.IS", "SAHOL.IS", "GARAN.IS", "AKBNK.IS",
    "PGSUS.IS", "SISE.IS", "TAVHL.IS", "TOASO.IS", "FROTO.IS",
    "PETKM.IS", "KRDMD.IS", "HEKTS.IS", "AYGAZ.IS", "ISCTR.IS",
    "YKBNK.IS", "HALKB.IS", "VAKBN.IS", "AKSA.IS", "ARCLK.IS",
    "CCOLA.IS", "CIMSA.IS", "CLEBI.IS", "ENJSA.IS", "ERBOS.IS",
    "FENIS.IS", "FMIZP.IS", "FORMT.IS", "GENTS.IS", "GLYHO.IS",
    "IPEKE.IS", "IZMDC.IS", "KARSN.IS", "KAYSE.IS", "KONTR.IS",
    "KORFM.IS", "LKMNH.IS", "MAKIM.IS", "MGROS.IS", "MRGYO.IS",
    "ODAS.IS", "PNLSN.IS", "PSDTC.IS", "SEKFK.IS", "SEKFS.IS",
    "SOKM.IS", "AEFES.IS", "AFYON.IS", "AKSEN.IS", "ALARK.IS",
    "ALKIM.IS", "ALTNY.IS", "ANACM.IS", "ARENA.IS", "ATAGY.IS",
    "ATATP.IS", "AVOD.IS", "AYDEM.IS", "BAGFS.IS", "BASGZ.IS",
    "BAYRK.IS", "BLCOM.IS", "BFRYS.IS", "BKENP.IS", "BKSST.IS",
    "BOBBR.IS", "BOMSN.IS", "BRISA.IS", "BRSAN.IS", "BRYAT.IS",
    "BSOKE.IS", "BTCIM.IS", "CANTE.IS", "CEMAS.IS", "CEMTS.IS",
    "CLDNM.IS", "CMBT.IS", "COSKUN.IS", "CRDFA.IS", "CUSAN.IS",
    "DAKOL.IS", "DENGE.IS", "DERIM.IS", "DESA.IS", "DEVA.IS",
    "DGKLB.IS", "DGGYO.IS", "DINBNK.IS", "DKRNK.IS", "DOAS.IS",
    "DOCO.IS", "DOHOL.IS", "ECZYO.IS", "EENFA.IS", "EGGUB.IS",
    "EKGYO.IS", "ELITE.IS", "EMKEL.IS", "ENKAI.IS", "ESCOM.IS",
    "EUPRO.IS", "EUREN.IS", "FADE.IS", "FENER.IS", "FLAP.IS",
    "FONET.IS", "FRIGO.IS", "GEDIK.IS", "GENIL.IS", "GESAN.IS",
    "GIPTA.IS", "GOLTS.IS", "GOODY.IS", "GOZDE.IS", "GRTHO.IS",
    "GSDHO.IS", "GUBRF.IS", "HASAN.IS", "HDFGS.IS", "HURGZ.IS",
    "HUSEIN.IS", "ICBCT.IS", "ICTURKEY.IS", "IDGIS.IS", "IHEVA.IS",
    "IHGZ.IS", "INDES.IS", "INFO.IS", "INGRM.IS",
]

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


settings = Settings()
