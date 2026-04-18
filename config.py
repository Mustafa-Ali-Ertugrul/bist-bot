"""Application configuration values and environment helpers."""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable with a safe fallback.

    Args:
        name: Environment variable name.
        default: Fallback value when the variable is missing or invalid.

    Returns:
        Parsed boolean value.
    """
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
    """Read an integer environment variable with a safe fallback.

    Args:
        name: Environment variable name.
        default: Fallback value when the variable is missing or invalid.

    Returns:
        Parsed integer value.
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_str_env(name: str, default: str = "") -> str:
    """Read a string environment variable and strip whitespace.

    Args:
        name: Environment variable name.
        default: Fallback value when the variable is missing.

    Returns:
        Normalized string value.
    """
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

WATCHLIST = DEFAULT_BIST100_WATCHLIST

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

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

SMA_FAST = 5
SMA_SLOW = 20

EMA_FAST = 12
EMA_SLOW = 26
EMA_LONG = 200

ADX_THRESHOLD = 20

VOLUME_CONFIRM_MULTIPLIER = 1.5

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2

VOLUME_SPIKE_MULTIPLIER = 1.5

DATA_PERIOD = "3mo"
DATA_INTERVAL = "1d"
MTF_ENABLED = _get_bool_env("MTF_ENABLED", True)
MTF_TREND_PERIOD = os.getenv("MTF_TREND_PERIOD", "6mo")
MTF_TREND_INTERVAL = os.getenv("MTF_TREND_INTERVAL", "1d")
MTF_TRIGGER_PERIOD = os.getenv("MTF_TRIGGER_PERIOD", "1mo")
MTF_TRIGGER_INTERVAL = os.getenv("MTF_TRIGGER_INTERVAL", "15m")
CORRELATION_THRESHOLD = float(os.getenv("CORRELATION_THRESHOLD", "0.70"))
CORRELATION_RISK_STEP = float(os.getenv("CORRELATION_RISK_STEP", "0.35"))
CORRELATION_MIN_SCALE = float(os.getenv("CORRELATION_MIN_SCALE", "0.25"))
CORRELATION_MAX_CLUSTER = _get_int_env("CORRELATION_MAX_CLUSTER", 2)
ATR_BASELINE_PCT = float(os.getenv("ATR_BASELINE_PCT", "0.025"))
ATR_MIN_RISK_SCALE = float(os.getenv("ATR_MIN_RISK_SCALE", "0.35"))

# Veri kaynagi: BIST web sitesi (~0-30sn) / Yahoo Finance (~15dk)
ENABLE_REALTIME_SCRAPING = _get_bool_env("ENABLE_REALTIME_SCRAPING", True)

# Rate limiting
RATE_LIMIT_SECONDS = float(os.getenv("RATE_LIMIT_SECONDS", "2.0"))

# Notification settings
NOTIFICATION_MAX_RETRIES = _get_int_env("NOTIFICATION_MAX_RETRIES", 3)
NOTIFICATION_RETRY_DELAY = _get_int_env("NOTIFICATION_RETRY_DELAY", 5)

TELEGRAM_BOT_TOKEN = _get_str_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get_str_env("TELEGRAM_CHAT_ID")

SCAN_INTERVAL_MINUTES = 15
MARKET_OPEN_HOUR = 10
MARKET_CLOSE_HOUR = 18
MARKET_WARMUP_MINUTES = 15
MARKET_HALF_DAY_HOUR = 13

FLASK_PORT = _get_int_env("FLASK_PORT", 5000)
FLASK_DEBUG = _get_bool_env("FLASK_DEBUG", False)

DB_PATH = _get_str_env("DB_PATH", "bist_signals.db")

INITIAL_CAPITAL = 8500.0

ML_SEQUENCE_LENGTH = 60
ML_EPOCHS = 50
ML_BATCH_SIZE = 32
ML_MODEL_PATH = "models"

BENCHMARK_TICKER = "^XU100"
BENCHMARK_TICKER_ALT = "XRXIST.IS"

PAPER_MODE = False
PAPER_TRADES_TABLE = "paper_trades"

COMMISSION_BUY = 0.0002
COMMISSION_SELL = 0.0002
BSMV = 0.0005
SLIPPAGE = 0.001

TELEGRAM_MIN_SCORE = 70

# Thresholds tuned to reduce over-signaling while keeping directional symmetry.
STRONG_BUY_THRESHOLD = 48
BUY_THRESHOLD = 20
WEAK_BUY_THRESHOLD = 8
WEAK_SELL_THRESHOLD = -8
SELL_THRESHOLD = -20
STRONG_SELL_THRESHOLD = -48

WALKFORWARD_TRAIN_DAYS = 180
WALKFORWARD_TEST_DAYS = 30

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

SECTOR_LIMIT = 2
