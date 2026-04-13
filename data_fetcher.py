import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast
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
    def __init__(self, watchlist: list[str] | None = None):
        self.watchlist = watchlist or config.WATCHLIST
        self._cache: dict[str, pd.DataFrame] = {}
        self._last_fetch: dict[str, datetime] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._max_workers = min(8, max(2, len(self.watchlist)))

    def _get_cached_data(self, ticker: str, force: bool = False) -> pd.DataFrame | None:
        if force:
            return None

        if ticker not in self._cache:
            return None

        last = self._last_fetch.get(ticker)
        if last and datetime.now() - last < self._cache_ttl:
            logger.debug(f"  {ticker} cache'den döndürüldü")
            return self._cache[ticker]

        return None

    def _normalize_history(self, ticker: str, df: pd.DataFrame | None) -> pd.DataFrame | None:
        if df is None or df.empty:
            logger.warning(f"⚠️  {ticker} için veri bulunamadı!")
            return None

        normalized = cast(pd.DataFrame, df.copy())
        normalized.columns = [str(col).lower() for col in normalized.columns]

        cols_to_keep = ["open", "high", "low", "close", "volume"]
        normalized = cast(pd.DataFrame, normalized[[c for c in cols_to_keep if c in normalized.columns]])

        if normalized.empty:
            logger.warning(f"⚠️  {ticker} için uygun fiyat kolonu bulunamadı!")
            return None

        normalized.index = pd.DatetimeIndex(pd.to_datetime(normalized.index)).tz_localize(None)

        if bool(normalized.isnull().to_numpy().sum()):
            normalized = cast(pd.DataFrame, normalized.dropna())
            logger.info(f"  {ticker}: NaN satırlar temizlendi")

        if normalized.empty:
            logger.warning(f"⚠️  {ticker} için temizleme sonrası veri kalmadı!")
            return None

        return cast(pd.DataFrame, normalized)

    def _store_cache(self, ticker: str, df: pd.DataFrame):
        self._cache[ticker] = df
        self._last_fetch[ticker] = datetime.now()

    def fetch_single(
        self,
        ticker: str,
        period: str | None = None,
        interval: str | None = None,
        force: bool = False
    ) -> pd.DataFrame | None:
        period = period or config.DATA_PERIOD
        interval = interval or config.DATA_INTERVAL

        cached = self._get_cached_data(ticker, force=force)
        if cached is not None:
            return cached

        try:
            logger.info(f"📥 {ticker} verisi çekiliyor...")

            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            df = self._normalize_history(ticker, df)
            if df is None:
                return None

            self._store_cache(ticker, df)

            logger.info(
                f"  ✅ {ticker}: {len(df)} mum, "
                f"Son kapanış: ₺{float(df['close'].iloc[-1]):.2f}"
            )
            return df

        except Exception as e:
            logger.error(f"❌ {ticker} veri çekme hatası: {e}")
            return None

    def fetch_all(
        self,
        period: str | None = None,
        interval: str | None = None
    ) -> dict[str, pd.DataFrame]:
        period = period or config.DATA_PERIOD
        interval = interval or config.DATA_INTERVAL

        results = {}
        total = len(self.watchlist)
        batch_start = time.perf_counter()

        logger.info(f"{'='*50}")
        logger.info(f"🔄 {total} hisse için veri çekiliyor...")
        logger.info(f"{'='*50}")

        missing_tickers = []
        for ticker in self.watchlist:
            cached = self._get_cached_data(ticker)
            if cached is not None:
                results[ticker] = cached
            else:
                missing_tickers.append(ticker)

        if missing_tickers:
            logger.info(
                f"⚡ Batch fetch başlıyor: {len(missing_tickers)} hisse "
                f"(cache hit: {len(results)})"
            )
            download_start = time.perf_counter()
            unresolved = list(missing_tickers)

            try:
                raw_data = yf.download(
                    tickers=" ".join(missing_tickers),
                    period=period,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                )

                if raw_data is not None and not raw_data.empty:
                    unresolved = []

                    for ticker in missing_tickers:
                        ticker_frame: pd.DataFrame | None
                        try:
                            if isinstance(raw_data.columns, pd.MultiIndex):
                                ticker_frame = cast(pd.DataFrame, raw_data[ticker])
                            else:
                                ticker_frame = cast(pd.DataFrame, raw_data)
                        except KeyError:
                            ticker_frame = None

                        df = self._normalize_history(ticker, ticker_frame)
                        if df is None:
                            unresolved.append(ticker)
                            continue

                        self._store_cache(ticker, df)
                        results[ticker] = df
                        logger.info(
                            f"  ✅ {ticker}: {len(df)} mum, "
                            f"Son kapanış: ₺{float(df['close'].iloc[-1]):.2f}"
                        )
                else:
                    logger.warning("⚠️  Batch download boş döndü, fallback başlatılıyor")

            except Exception as e:
                logger.warning(f"⚠️  Batch download hatası: {e}")

            logger.info(
                f"⏱️  Batch fetch süresi: "
                f"{time.perf_counter() - download_start:.2f}s"
            )

            if unresolved:
                logger.info(
                    f"🔁 Fallback parallel fetch başlıyor: {len(unresolved)} hisse"
                )
                fallback_start = time.perf_counter()

                with ThreadPoolExecutor(max_workers=min(self._max_workers, len(unresolved))) as executor:
                    future_map = {
                        executor.submit(self.fetch_single, ticker, period, interval, True): ticker
                        for ticker in unresolved
                    }

                    for future in as_completed(future_map):
                        ticker = future_map[future]
                        try:
                            df = future.result()
                            if df is not None:
                                results[ticker] = df
                        except Exception as e:
                            logger.error(f"❌ {ticker} fallback hatası: {e}")

                logger.info(
                    f"⏱️  Fallback fetch süresi: "
                    f"{time.perf_counter() - fallback_start:.2f}s"
                )

        success = len(results)
        fail = total - success
        logger.info(f"{'='*50}")
        logger.info(f"📊 Sonuç: {success} başarılı, {fail} başarısız")
        logger.info(f"⏱️  Toplam fetch_all süresi: {time.perf_counter() - batch_start:.2f}s")
        logger.info(f"{'='*50}")

        return results

    def get_current_price(self, ticker: str) -> float | None:
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
