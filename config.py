import os
from dotenv import load_dotenv

load_dotenv()


WATCHLIST = [
    "ASELS.IS",
    "THYAO.IS",
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
]

TICKER_NAMES = {
    "ASELS.IS": "ASELSAN",
    "THYAO.IS": "THY",
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
}


RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

SMA_FAST = 5
SMA_SLOW = 20

EMA_FAST = 12
EMA_SLOW = 26

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

FLASK_PORT = 5000
FLASK_DEBUG = True

DB_PATH = "bist_signals.db"
