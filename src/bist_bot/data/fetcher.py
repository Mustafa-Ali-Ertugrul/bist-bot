"""Market data fetching helpers for BIST symbols."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from typing import Any, cast

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.data.bist100 import BIST100_TICKERS
from bist_bot.data import helpers as fetch_helpers
from bist_bot.data import quotes as fetch_quotes
from bist_bot.data.providers import BorsaIstanbulQuoteProvider, MarketDataProvider, OfficialProviderStub, QuoteProvider, YFinanceProvider

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    value: Any
    cached_at: datetime


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
    provider = YFinanceProvider(_rate_limiter)
    return fetch_helpers.fetch_history_with_provider(provider, ticker, period, interval)


class BISTDataFetcher:
    """BIST hisseleri icin veri cekme ve cache yonetimi yapar.

    Watchlist olusturma, toplu veya tekil veri indirme ve kisa sureli bellek
    ici cache davranisini tek bir servis altinda toplar.

    Attributes:
        watchlist: Normalize edilmis hisse listesi.
        _cache: Ticker bazli veri cache'i.
        _last_fetch: Her ticker icin son veri cekim zamani.
    """

    def __init__(
        self,
        watchlist: list[str] | None = None,
        provider: MarketDataProvider | None = None,
        quote_provider: QuoteProvider | None = None,
    ) -> None:
        """Initialize the fetcher with a normalized watchlist.

        Args:
            watchlist: Optional explicit ticker list.
        """
        self.provider = provider or YFinanceProvider(_rate_limiter)
        self.quote_provider = quote_provider or BorsaIstanbulQuoteProvider(_rate_limiter)
        if watchlist is None:
            tickers = self.provider.fetch_universe()
            if len(tickers) < 90:
                logger.warning(f"⚠️ Watchlist yetersiz ({len(tickers)}), fallback kullaniliyor")
                tickers = _clean_ticker_list(BIST100_TICKERS)
            self.watchlist = tickers
        else:
            self.watchlist = _clean_ticker_list(watchlist)
        self._history_cache: dict[tuple[str, str, str], CacheEntry] = {}
        self._analysis_cache: dict[str, CacheEntry] = {}
        self._quote_cache: dict[str, CacheEntry] = {}
        self._max_workers = min(8, max(2, len(self.watchlist)))
        logger.info(f"BISTDataFetcher baslatildi: {len(self.watchlist)} hisse")

    def _cache_key(self, ticker: str, period: str, interval: str) -> tuple[str, str, str]:
        return (ticker, period, interval)

    def _now(self) -> datetime:
        return datetime.now()

    def _is_intraday_interval(self, interval: str) -> bool:
        normalized = interval.strip().lower()
        return normalized.endswith(("m", "h"))

    def _history_ttl(self, interval: str) -> timedelta:
        if self._is_intraday_interval(interval):
            return timedelta(seconds=float(getattr(settings, "INTRADAY_FETCH_CACHE_TTL_SECONDS", 120)))
        return timedelta(seconds=float(getattr(settings, "FETCH_CACHE_TTL_SECONDS", 900)))

    def _analysis_ttl(self) -> timedelta:
        return timedelta(seconds=float(getattr(settings, "ANALYSIS_CACHE_TTL_SECONDS", 180)))

    def _quote_ttl(self) -> timedelta:
        return timedelta(seconds=float(getattr(settings, "REALTIME_QUOTE_CACHE_TTL_SECONDS", 30)))

    def _get_valid_cache_entry(self, cache: dict[Any, CacheEntry], cache_key: Any, ttl: timedelta) -> Any | None:
        entry = cache.get(cache_key)
        if entry is None:
            return None
        if self._now() - entry.cached_at < ttl:
            return entry.value
        cache.pop(cache_key, None)
        return None

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
        cached = self._get_valid_cache_entry(self._history_cache, cache_key, self._history_ttl(interval))
        if cached is not None:
            logger.debug(f"  {ticker} cache'den döndürüldü ({interval}/{period})")
            return cast(pd.DataFrame, cached)
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
        self._history_cache[cache_key] = CacheEntry(value=df, cached_at=self._now())
        self.clear_cache(scope="analysis", ticker=ticker)

    def get_cached_analysis(self, cache_key: str, force: bool = False) -> Any | None:
        if force:
            return None
        return self._get_valid_cache_entry(self._analysis_cache, cache_key, self._analysis_ttl())

    def store_analysis(self, cache_key: str, value: Any) -> None:
        self._analysis_cache[cache_key] = CacheEntry(value=value, cached_at=self._now())

    def get_cached_quote(self, ticker: str, force: bool = False) -> float | None:
        if force:
            return None
        cached = self._get_valid_cache_entry(self._quote_cache, ticker, self._quote_ttl())
        if cached is None:
            return None
        return float(cached)

    def _store_quote(self, ticker: str, price: float) -> None:
        self._quote_cache[ticker] = CacheEntry(value=float(price), cached_at=self._now())

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
        normalized_ticker = normalize_ticker(ticker)

        cached = self._get_cached_data(normalized_ticker, period, interval, force=force)
        if cached is not None:
            return cached

        try:
            logger.info(f"📥 {normalized_ticker} verisi çekiliyor...")

            raw_df = fetch_helpers.fetch_history_with_provider(
                self.provider,
                normalized_ticker,
                period=period,
                interval=interval,
            )
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
        interval: str | None = None,
        force: bool = False,
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
            cached = self._get_cached_data(ticker, period, interval, force=force)
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
                raw_batch = self.provider.fetch_batch(
                    missing_tickers,
                    period=period,
                    interval=interval,
                )

                if raw_batch:
                    unresolved = []

                    for ticker in missing_tickers:
                        ticker_frame = raw_batch.get(ticker)

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
        ticker = normalize_ticker(ticker)
        cached = self.get_cached_quote(ticker)
        if cached is not None:
            logger.debug("⚡ %s realtime fiyat cache hit", ticker)
            return cached

        if getattr(settings, "ENABLE_REALTIME_SCRAPING", True):
            try:
                scraped_price = self.quote_provider.fetch_quote(ticker)
            except Exception as exc:
                scraped_price = None
                logger.warning("⚠️ %s realtime quote beklenmeyen hatayla başarısız oldu: %s", ticker, exc)

            if scraped_price is not None:
                self._store_quote(ticker, float(scraped_price))
                logger.info("⚡ %s realtime fiyat quote provider ile alındı", ticker)
                return float(scraped_price)

            provider_quote = self.provider.fetch_quote(ticker)
            if provider_quote is not None:
                self._store_quote(ticker, float(provider_quote))
                logger.info("⚡ %s realtime fiyat primary provider ile alındı", ticker)
                return float(provider_quote)

        df = self.fetch_single(ticker, period="5d", interval="1d")
        if df is not None and not df.empty:
            self._store_quote(ticker, float(df["close"].iloc[-1]))
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
            import yfinance as yf

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

    def clear_cache(
        self,
        scope: str = "all",
        ticker: str | None = None,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        """Clear cached entries selectively instead of dropping every cache bucket."""
        normalized_ticker = normalize_ticker(ticker) if ticker else None

        if scope in {"all", "history", "intraday_fetch"}:
            history_keys = [
                key
                for key in list(self._history_cache)
                if (normalized_ticker is None or key[0] == normalized_ticker)
                and (period is None or key[1] == period)
                and (interval is None or key[2] == interval)
                and (scope != "intraday_fetch" or self._is_intraday_interval(key[2]))
            ]
            for key in history_keys:
                self._history_cache.pop(key, None)

        if scope in {"all", "analysis"}:
            analysis_keys = [
                key
                for key in list(self._analysis_cache)
                if normalized_ticker is None or key.startswith(f"{normalized_ticker}|")
            ]
            for key in analysis_keys:
                self._analysis_cache.pop(key, None)

        if scope in {"all", "quote_fallback"}:
            if normalized_ticker is None:
                self._quote_cache.clear()
            else:
                self._quote_cache.pop(normalized_ticker, None)

        logger.info("🗑️  Cache temizlendi (scope=%s)", scope)

    def fetch_multi_timeframe_all(
        self,
        trend_period: str | None = None,
        trend_interval: str | None = None,
        trigger_period: str | None = None,
        trigger_interval: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, dict[str, pd.DataFrame]]:
        trend_period = trend_period or getattr(settings, "MTF_TREND_PERIOD", "6mo")
        trend_interval = trend_interval or getattr(settings, "MTF_TREND_INTERVAL", "1d")
        trigger_period = trigger_period or getattr(settings, "MTF_TRIGGER_PERIOD", "1mo")
        trigger_interval = trigger_interval or getattr(settings, "MTF_TRIGGER_INTERVAL", "15m")

        trend_data = self.fetch_all(period=trend_period, interval=trend_interval, force=force_refresh)
        trigger_data = self.fetch_all(period=trigger_period, interval=trigger_interval, force=force_refresh)

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


__all__ = [
    "BISTDataFetcher",
    "BorsaIstanbulQuoteProvider",
    "MarketDataProvider",
    "OfficialProviderStub",
    "QuoteProvider",
    "RateLimiter",
    "YFinanceProvider",
    "_rate_limiter",
]
