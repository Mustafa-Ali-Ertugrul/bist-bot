import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import logging
import time

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


class BISTDataFetcher:
    def __init__(self, watchlist: list[str] = None):
        self.watchlist = watchlist or config.WATCHLIST
        self._cache: dict[str, pd.DataFrame] = {}
        self._last_fetch: dict[str, datetime] = {}
        self._cache_ttl = timedelta(minutes=5)

    def fetch_single(
        self,
        ticker: str,
        period: str = None,
        interval: str = None,
        force: bool = False
    ) -> Optional[pd.DataFrame]:
        period = period or config.DATA_PERIOD
        interval = interval or config.DATA_INTERVAL

        if not force and ticker in self._cache:
            last = self._last_fetch.get(ticker)
            if last and datetime.now() - last < self._cache_ttl:
                logger.debug(f"  {ticker} cache'den döndürüldü")
                return self._cache[ticker]

        try:
            logger.info(f"📥 {ticker} verisi çekiliyor...")

            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"⚠️  {ticker} için veri bulunamadı!")
                return None

            df.columns = [col.lower() for col in df.columns]

            cols_to_keep = ["open", "high", "low", "close", "volume"]
            df = df[[c for c in cols_to_keep if c in df.columns]]

            df.index = pd.to_datetime(df.index)
            df.index = df.index.tz_localize(None)

            if df.isnull().any().any():
                df = df.dropna()
                logger.info(f"  {ticker}: NaN satırlar temizlendi")

            self._cache[ticker] = df
            self._last_fetch[ticker] = datetime.now()

            logger.info(
                f"  ✅ {ticker}: {len(df)} mum, "
                f"Son kapanış: ₺{df['close'].iloc[-1]:.2f}"
            )
            return df

        except Exception as e:
            logger.error(f"❌ {ticker} veri çekme hatası: {e}")
            return None

    def fetch_all(
        self,
        period: str = None,
        interval: str = None
    ) -> dict[str, pd.DataFrame]:
        results = {}
        total = len(self.watchlist)

        logger.info(f"{'='*50}")
        logger.info(f"🔄 {total} hisse için veri çekiliyor...")
        logger.info(f"{'='*50}")

        for i, ticker in enumerate(self.watchlist, 1):
            logger.info(f"[{i}/{total}] {ticker}")
            df = self.fetch_single(ticker, period, interval)

            if df is not None:
                results[ticker] = df

            if i < total:
                time.sleep(0.5)

        success = len(results)
        fail = total - success
        logger.info(f"{'='*50}")
        logger.info(f"📊 Sonuç: {success} başarılı, {fail} başarısız")
        logger.info(f"{'='*50}")

        return results

    def get_current_price(self, ticker: str) -> Optional[float]:
        df = self.fetch_single(ticker, period="5d", interval="1d")
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
        return None

    def get_stock_info(self, ticker: str) -> dict:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            return {
                "name": info.get("shortName", ticker),
                "sector": info.get("sector", "Bilinmiyor"),
                "market_cap": info.get("marketCap", 0),
                "pe_ratio": info.get("trailingPE", None),
                "52w_high": info.get("fiftyTwoWeekHigh", None),
                "52w_low": info.get("fiftyTwoWeekLow", None),
            }
        except Exception as e:
            logger.error(f"Bilgi çekme hatası ({ticker}): {e}")
            return {}

    def clear_cache(self):
        self._cache.clear()
        self._last_fetch.clear()
        logger.info("🗑️  Cache temizlendi")


if __name__ == "__main__":
    fetcher = BISTDataFetcher()

    df = fetcher.fetch_single("ASELS.IS")
    if df is not None:
        print("\n📈 ASELSAN Son 5 Gün:")
        print(df.tail())
        print(f"\nSon Fiyat: ₺{df['close'].iloc[-1]:.2f}")
        print(f"Toplam Veri: {len(df)} mum")
