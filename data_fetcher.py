"""Market data fetching helpers for BIST symbols."""

import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast
import logging
import time

import yfinance as yf

from config import settings
from data.bist100 import BIST100_TICKERS
import data_fetcher_helpers as fetch_helpers
import data_fetcher_quotes as fetch_quotes
from data_fetcher_scraper import scrape_bist_quote

logger = logging.getLogger(__name__)


class RateLimiter:
    """Basit rate limiter.

    Her domain icin son istek zamanini izler ve minimum bekleme suresi
    uygulanarak ardisik isteklerin cok sik gonderilmesini engeller.
    """

    def __init__(self):
        self.last_request: dict[str, float] = {}

    def wait_if_needed(self, domain: str) -> None:
        current_time = time.time()
        min_interval = float(getattr(settings, "RATE_LIMIT_SECONDS", 2.0))
        last_request = self.last_request.get(domain)
        if last_request is not None:
            elapsed = current_time - last_request
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self.last_request[domain] = time.time()


_rate_limiter = RateLimiter()


def _parse_tr_number(raw: str) -> float | None:
    return fetch_quotes.parse_tr_number(raw)


def _clean_ticker_list(tickers: list[str]) -> list[str]:
    return fetch_helpers.clean_ticker_list(tickers)


def normalize_ticker(ticker: str) -> str:
    return fetch_helpers.normalize_ticker(ticker)


def validate_data(df: pd.DataFrame | None, min_rows: int = 5) -> bool:
    return fetch_helpers.validate_data(df, min_rows=min_rows)


def get_bist100_tickers(force_refresh: bool = False) -> list[str]:
    return fetch_quotes.get_bist100_tickers(_rate_limiter, force_refresh=force_refresh)


def get_price_from_bist_website(ticker: str) -> dict[str, float | str] | None:
    return fetch_quotes.get_price_from_bist_website(ticker, _rate_limiter)


def fetch_with_fallback(ticker: str, period: str, interval: str) -> pd.DataFrame | None:
    return fetch_helpers.fetch_with_fallback(ticker, period, interval, _rate_limiter)


class BISTDataFetcher:
    """BIST hisseleri icin veri cekme ve cache yonetimi yapar.

    Watchlist olusturma, toplu veya tekil veri indirme ve kisa sureli bellek
    ici cache davranisini tek bir servis altinda toplar.

    Attributes:
        watchlist: Normalize edilmis hisse listesi.
        _cache: Ticker bazli veri cache'i.
        _last_fetch: Her ticker icin son veri cekim zamani.
    """

    def __init__(self, watchlist: list[str] | None = None) -> None:
        """Initialize the fetcher with a normalized watchlist.

        Args:
            watchlist: Optional explicit ticker list.
        """
        if watchlist is None:
            tickers = get_bist100_tickers()
            if len(tickers) < 90:
                logger.warning(f"⚠️ Watchlist yetersiz ({len(tickers)}), fallback kullaniliyor")
                tickers = _clean_ticker_list(BIST100_TICKERS)
            self.watchlist = tickers
        else:
            self.watchlist = _clean_ticker_list(watchlist)
        self._cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._last_fetch: dict[tuple[str, str, str], datetime] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._max_workers = min(8, max(2, len(self.watchlist)))
        logger.info(f"BISTDataFetcher baslatildi: {len(self.watchlist)} hisse")

    def _cache_key(self, ticker: str, period: str, interval: str) -> tuple[str, str, str]:
        return (ticker, period, interval)

    def _get_cached_data(
        self,
        ticker: str,
        period: str,
        interval: str,
        force: bool = False,
    ) -> pd.DataFrame | None:
        """Return cached data for a ticker when the cache entry is still fresh.

        Args:
            ticker: Stock symbol.
            force: Ignore cache when ``True``.

        Returns:
            Cached price dataframe or ``None``.
        """
        if force:
            return None

        cache_key = self._cache_key(ticker, period, interval)
        if cache_key not in self._cache:
            return None

        last = self._last_fetch.get(cache_key)
        if last and datetime.now() - last < self._cache_ttl:
            logger.debug(f"  {ticker} cache'den döndürüldü ({interval}/{period})")
            return self._cache[cache_key]

        return None

    def _normalize_history(self, ticker: str, df: pd.DataFrame | None) -> pd.DataFrame | None:
        """Normalize downloaded price history into the expected schema.

        Args:
            ticker: Stock symbol.
            df: Raw dataframe returned by the data source.

        Returns:
            Cleaned dataframe or ``None`` when the payload is unusable.
        """
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

    def _store_cache(self, ticker: str, period: str, interval: str, df: pd.DataFrame) -> None:
        """Store normalized price history in the in-memory cache.

        Args:
            ticker: Stock symbol.
            df: Normalized dataframe to cache.
        """
        cache_key = self._cache_key(ticker, period, interval)
        self._cache[cache_key] = df
        self._last_fetch[cache_key] = datetime.now()

    def fetch_single(
        self,
        ticker: str,
        period: str | None = None,
        interval: str | None = None,
        force: bool = False
    ) -> pd.DataFrame | None:
        """Fetch price history for a single ticker.

        Args:
            ticker: Stock symbol.
            period: Data source lookback period.
            interval: Candle interval.
            force: Ignore cache when ``True``.

        Returns:
            Normalized price dataframe or ``None`` on failure.
        """
        period = period or settings.DATA_PERIOD
        interval = interval or settings.DATA_INTERVAL

        cached = self._get_cached_data(ticker, period, interval, force=force)
        if cached is not None:
            return cached

        try:
            normalized_ticker = normalize_ticker(ticker)
            logger.info(f"📥 {normalized_ticker} verisi çekiliyor...")

            raw_df = fetch_with_fallback(normalized_ticker, period=period, interval=interval)
            df = self._normalize_history(normalized_ticker, raw_df)
            if df is None:
                return None

            self._store_cache(normalized_ticker, period, interval, df)

            logger.info(
                f"  ✅ {normalized_ticker}: {len(df)} mum, "
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
        """Fetch price history for the entire watchlist.

        Args:
            period: Data source lookback period.
            interval: Candle interval.

        Returns:
            Mapping of ticker symbols to normalized dataframes.
        """
        period = period or settings.DATA_PERIOD
        interval = interval or settings.DATA_INTERVAL

        results = {}
        total = len(self.watchlist)
        batch_start = time.perf_counter()

        logger.info(f"{'='*50}")
        logger.info(f"🔄 {total} hisse için veri çekiliyor...")
        logger.info(f"{'='*50}")

        missing_tickers = []
        for ticker in self.watchlist:
            cached = self._get_cached_data(ticker, period, interval)
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
                _rate_limiter.wait_if_needed("yahoo.finance")
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

                        self._store_cache(ticker, period, interval, df)
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
        """Return the latest price using realtime scraping with Yahoo fallback.

        Args:
            ticker: Stock symbol.

        Returns:
            Latest price if available, otherwise ``None``.
        """
        if getattr(settings, "ENABLE_REALTIME_SCRAPING", True):
            try:
                scraped_result = scrape_bist_quote(ticker, _rate_limiter)
            except Exception as exc:
                scraped_result = None
                logger.warning("⚠️ %s realtime scrape beklenmeyen hatayla başarısız oldu: %s", ticker, exc)

            if scraped_result and scraped_result.success and scraped_result.price is not None:
                logger.info("⚡ %s realtime fiyat scrape ile alındı", ticker)
                return float(scraped_result.price)

            if scraped_result is not None:
                logger.info(
                    "↩️ %s scrape başarısız (%s); Yahoo fallback kullanılacak",
                    ticker,
                    scraped_result.detail or "bilinmeyen-neden",
                )

        df = self.fetch_single(ticker, period="5d", interval="1d")
        if df is not None and not df.empty:
            logger.info("📉 %s fiyatı Yahoo history fallback ile alındı", ticker)
            return float(df["close"].iloc[-1])

        logger.error("❌ %s için realtime scrape ve Yahoo fallback birlikte başarısız oldu", ticker)
        return None

    def get_stock_info(self, ticker: str) -> dict[str, str | int | float | None]:
        """Fetch descriptive stock metadata from Yahoo Finance.

        Args:
            ticker: Stock symbol.

        Returns:
            Dictionary of basic company metadata.
        """
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

    def clear_cache(self) -> None:
        """Clear all cached price history entries."""
        self._cache.clear()
        self._last_fetch.clear()
        logger.info("🗑️  Cache temizlendi")

    def fetch_multi_timeframe_all(
        self,
        trend_period: str | None = None,
        trend_interval: str | None = None,
        trigger_period: str | None = None,
        trigger_interval: str | None = None,
    ) -> dict[str, dict[str, pd.DataFrame]]:
        trend_period = trend_period or getattr(settings, "MTF_TREND_PERIOD", "6mo")
        trend_interval = trend_interval or getattr(settings, "MTF_TREND_INTERVAL", "1d")
        trigger_period = trigger_period or getattr(settings, "MTF_TRIGGER_PERIOD", "1mo")
        trigger_interval = trigger_interval or getattr(settings, "MTF_TRIGGER_INTERVAL", "15m")

        trend_data = self.fetch_all(period=trend_period, interval=trend_interval)
        trigger_data = self.fetch_all(period=trigger_period, interval=trigger_interval)

        combined: dict[str, dict[str, pd.DataFrame]] = {}
        for ticker in self.watchlist:
            trend_df = trend_data.get(ticker)
            trigger_df = trigger_data.get(ticker)
            if trend_df is None or trigger_df is None:
                continue
            combined[ticker] = {"trend": trend_df, "trigger": trigger_df}
        return combined


if __name__ == "__main__":
    fetcher = BISTDataFetcher()

    df = fetcher.fetch_single("ASELS.IS")
    if df is not None:
        print("\n📈 ASELSAN Son 5 Gün:")
        print(df.tail())
        print(f"\nSon Fiyat: ₺{df['close'].iloc[-1]:.2f}")
        print(f"Toplam Veri: {len(df)} mum")
