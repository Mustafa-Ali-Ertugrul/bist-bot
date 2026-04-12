import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


WATCHLIST = [
    "THYAO.IS",
    "ASELS.IS",
    "SASA.IS",
    "KCHOL.IS",
    "EREGL.IS",
    "BIMAS.IS",
    "TUPRS.IS",
    "SAHOL.IS",
    "GARAN.IS",
    "AKBNK.IS",
    "PGSUS.IS",
    "SISE.IS",
    "TAVHL.IS",
    "TOASO.IS",
    "FROTO.IS",
    "PETKM.IS",
    "KRDMD.IS",
    "HEKTS.IS",
    "AYGAZ.IS",
    "ISCTR.IS",
    "YKBNK.IS",
    "HALKB.IS",
    "VAKBN.IS",
    "AKSA.IS",
    "ARCLK.IS",
    "CCOLA.IS",
    "CIMSA.IS",
    "CLEBI.IS",
    "ENJSA.IS",
    "ERBOS.IS",
    "FENIS.IS",
    "FMIZP.IS",
    "FORMT.IS",
    "GENTS.IS",
    "GLYHO.IS",
    "IPEKE.IS",
    "IZMDC.IS",
    "KARSN.IS",
    "KAYSE.IS",
    "KONTR.IS",
    "KORFM.IS",
    "LKMNH.IS",
    "MAKIM.IS",
    "MGROS.IS",
    "MRGYO.IS",
    "ODAS.IS",
    "PNLSN.IS",
    "PSDTC.IS",
    "SEKFK.IS",
    "SEKFS.IS",
    "SOKM.IS",
]

TICKER_NAMES = {
    "THYAO.IS": "THY",
    "ASELS.IS": "ASELSAN",
    "SASA.IS": "SASA",
    "KCHOL.IS": "Koç Holding",
    "EREGL.IS": "Ereğli",
    "BIMAS.IS": "BİM",
    "TUPRS.IS": "Tüpraş",
    "SAHOL.IS": "Sabancı",
    "GARAN.IS": "Garanti",
    "AKBNK.IS": "Akbank",
    "PGSUS.IS": "Pegasus",
    "SISE.IS": "Şişecam",
    "TAVHL.IS": "TAV",
    "TOASO.IS": "Tofaş",
    "FROTO.IS": "Ford Otosan",
    "PETKM.IS": "Petkim",
    "KRDMD.IS": "Kardemir",
    "HEKTS.IS": "Hektaş",
    "AYGAZ.IS": "Aygaç",
    "ISCTR.IS": "İş Bankası",
    "YKBNK.IS": "Yapı Kredi",
    "HALKB.IS": "Halkbank",
    "VAKBN.IS": "VakıfBank",
    "AKSA.IS": "Aksa",
    "ARCLK.IS": "Arçelik",
    "CCOLA.IS": "Coca Cola",
    "CIMSA.IS": "Çimsa",
    "CLEBI.IS": "Clebi",
    "ENJSA.IS": "Enjsa",
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
    "SOKM.IS": "Sök",
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SCAN_INTERVAL_MINUTES = 15
MARKET_OPEN_HOUR = 10
MARKET_CLOSE_HOUR = 18
MARKET_WARMUP_MINUTES = 15
MARKET_HALF_DAY_HOUR = 13

FLASK_PORT = 5000
FLASK_DEBUG = True

DB_PATH = "bist_signals.db"

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

STRONG_BUY_THRESHOLD = 40
BUY_THRESHOLD = 10
WEAK_BUY_THRESHOLD = 0
WEAK_SELL_THRESHOLD = 0
SELL_THRESHOLD = -10
STRONG_SELL_THRESHOLD = -40

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
