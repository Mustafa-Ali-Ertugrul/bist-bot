"""Market data fetching helpers for BIST symbols."""

# Standard library imports
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

# Third-party imports
import pandas as pd

from bist_bot.app_logging import get_logger

# Local application imports
from bist_bot.app_metrics import inc_counter, set_gauge
from bist_bot.config.settings import settings
from bist_bot.data import helpers as fetch_helpers
from bist_bot.data import quotes as fetch_quotes
from bist_bot.data.bist100 import BIST100_TICKERS
from bist_bot.data.providers import (
    BorsaIstanbulQuoteProvider,
    DataProviderRouter,
    MarketDataProvider,
    OfficialProvider,
    OfficialProviderStub,
    QuoteProvider,
    YFinanceProvider,
)
from bist_bot.data.schemas import validate_dataframe

logger = get_logger(__name__, component="data_fetcher")


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
            tickers = _clean_ticker_list(self.provider.fetch_universe())
            if len(tickers) < 90:
                logger.warning(
                    "watchlist_provider_insufficient",
                    provider_count=len(tickers),
                )
            if not tickers:
                tickers = _clean_ticker_list(BIST100_TICKERS)
                logger.warning(
                    "watchlist_static_fallback",
                    fallback_count=len(tickers),
                )
            self.watchlist = tickers
        else:
            self.watchlist = _clean_ticker_list(watchlist)
        self._history_cache: dict[tuple[str, str, str], CacheEntry] = {}
        self._analysis_cache: dict[str, CacheEntry] = {}
        self._quote_cache: dict[str, CacheEntry] = {}
        self._max_workers = min(8, max(2, len(self.watchlist)))
        logger.info("fetcher_initialized", watchlist_size=len(self.watchlist))

    def _cache_key(self, ticker: str, period: str, interval: str) -> tuple[str, str, str]:
        return (ticker, period, interval)

    def _now(self) -> datetime:
        return datetime.now()

    def _is_intraday_interval(self, interval: str) -> bool:
        normalized = interval.strip().lower()
        return normalized.endswith(("m", "h"))

    def _history_ttl(self, interval: str) -> timedelta:
        if self._is_intraday_interval(interval):
            return timedelta(
                seconds=float(getattr(settings, "INTRADAY_FETCH_CACHE_TTL_SECONDS", 120))
            )
        return timedelta(seconds=float(getattr(settings, "FETCH_CACHE_TTL_SECONDS", 900)))

    def _analysis_ttl(self) -> timedelta:
        return timedelta(seconds=float(getattr(settings, "ANALYSIS_CACHE_TTL_SECONDS", 180)))

    def _quote_ttl(self) -> timedelta:
        return timedelta(seconds=float(getattr(settings, "REALTIME_QUOTE_CACHE_TTL_SECONDS", 30)))

    def _get_valid_cache_entry(
        self, cache: dict[Any, CacheEntry], cache_key: Any, ttl: timedelta
    ) -> Any | None:
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
        cached = self._get_valid_cache_entry(
            self._history_cache, cache_key, self._history_ttl(interval)
        )
        if cached is not None:
            logger.debug("cache_hit", ticker=ticker, interval=interval, period=period)
            return cast(pd.DataFrame, cached)
        return None

    def _normalize_history(
        self, ticker: str, df: pd.DataFrame | None, validate: bool = True
    ) -> pd.DataFrame | None:
        """Normalize downloaded price history into the expected schema.

        Args:
            ticker: Stock symbol.
            df: Raw dataframe returned by the data source.
            validate: Ensure clean dataframe schema.

        Returns:
            Cleaned dataframe or ``None`` when the payload is unusable.
        """
        valid_df = validate_dataframe(df, validate=validate)
        if valid_df is None or valid_df.empty:
            logger.warning("invalid_data_schema", ticker=ticker)
            return None
        return valid_df

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
        force: bool = False,
        validate: bool = True,
    ) -> pd.DataFrame | None:
        """Fetch price history for a single ticker.

        Args:
            ticker: Stock symbol.
            period: Data source lookback period.
            interval: Candle interval.
            force: Ignore cache when ``True``.
            validate: Ensure clean dataframe schema.

        Returns:
            Normalized price dataframe or ``None`` on failure.
        """
        period = period or settings.DATA_PERIOD
        interval = interval or settings.DATA_INTERVAL
        normalized_ticker = normalize_ticker(ticker)

        cached = self._get_cached_data(normalized_ticker, period, interval, force=force)
        if cached is not None:
            logger.debug(
                "history_cache_hit",
                ticker=normalized_ticker,
                interval=interval,
                period=period,
            )
            return cached

        try:
            logger.info(
                "history_fetch_started",
                ticker=normalized_ticker,
                period=period,
                interval=interval,
            )

            raw_df = fetch_helpers.fetch_history_with_provider(
                self.provider,
                normalized_ticker,
                period=period,
                interval=interval,
            )
            df = self._normalize_history(normalized_ticker, raw_df, validate=validate)
            if df is None:
                return None

            self._store_cache(normalized_ticker, period, interval, df)

            logger.info(
                "history_fetch_succeeded",
                ticker=normalized_ticker,
                candle_count=len(df),
                last_close=round(float(df["close"].iloc[-1]), 2),
            )
            return df

        except Exception as e:
            logger.error(
                "history_fetch_failed",
                ticker=normalized_ticker,
                error_type=type(e).__name__,
            )
            return None

    def fetch_all(
        self,
        period: str | None = None,
        interval: str | None = None,
        force: bool = False,
        validate: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """Fetch price history for the entire watchlist.

        Args:
            period: Data source lookback period.
            interval: Candle interval.
            force: Ignore cache when ``True``.
            validate: Ensure clean dataframe schema.

        Returns:
            Mapping of ticker symbols to normalized dataframes.
        """
        period = period or settings.DATA_PERIOD
        interval = interval or settings.DATA_INTERVAL

        results = {}
        outcomes: dict[str, str] = {}
        total = len(self.watchlist)
        batch_start = time.perf_counter()

        logger.info("batch_fetch_started", ticker_count=total)

        missing_tickers = []
        for ticker in self.watchlist:
            cached = self._get_cached_data(ticker, period, interval, force=force)
            if cached is not None:
                results[ticker] = cached
                outcomes[ticker] = "skipped"
            else:
                missing_tickers.append(ticker)

        if missing_tickers:
            logger.info(
                "provider_batch_started",
                missing_count=len(missing_tickers),
                cache_hit_count=len(results),
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

                        df = self._normalize_history(ticker, ticker_frame, validate=validate)
                        if df is None:
                            unresolved.append(ticker)
                            continue

                        self._store_cache(ticker, period, interval, df)
                        results[ticker] = df
                        outcomes[ticker] = "success"
                        logger.info(
                            "provider_batch_ticker_succeeded",
                            ticker=ticker,
                            candle_count=len(df),
                            last_close=round(float(df["close"].iloc[-1]), 2),
                        )
                else:
                    logger.warning("provider_batch_empty_response")

            except Exception as e:
                logger.warning(
                    "provider_batch_failed",
                    error_type=type(e).__name__,
                )

            logger.info(
                "provider_batch_finished",
                duration_seconds=round(time.perf_counter() - download_start, 2),
            )

            if unresolved:
                logger.info(
                    "provider_fallback_started",
                    unresolved_count=len(unresolved),
                )
                fallback_start = time.perf_counter()

                with ThreadPoolExecutor(
                    max_workers=min(self._max_workers, len(unresolved))
                ) as executor:
                    future_map = {
                        executor.submit(
                            self.fetch_single, ticker, period, interval, True, validate
                        ): ticker
                        for ticker in unresolved
                    }

                    for future in as_completed(future_map):
                        ticker = future_map[future]
                        try:
                            df = future.result()
                            if df is not None:
                                results[ticker] = df
                                outcomes[ticker] = "fallback_success"
                                logger.info("provider_fallback_succeeded", ticker=ticker)
                            else:
                                outcomes[ticker] = "failed"
                        except Exception as e:
                            outcomes[ticker] = "failed"
                            logger.error(
                                "provider_fallback_failed",
                                ticker=ticker,
                                error_type=type(e).__name__,
                            )

                logger.info(
                    "provider_fallback_finished",
                    duration_seconds=round(time.perf_counter() - fallback_start, 2),
                )

        success = len(results)
        fail = total - success
        for ticker in self.watchlist:
            outcomes.setdefault(ticker, "failed")
        coverage_pct = (success / total * 100) if total else 0.0
        for outcome in outcomes.values():
            inc_counter(f"bist_provider_fetch_outcome_{outcome}_total")
        set_gauge("bist_provider_fetch_coverage_pct", coverage_pct)
        set_gauge("bist_provider_fetch_failed_count", fail)
        logger.info(
            "fetch_all_coverage",
            total=total,
            success=success,
            failed=fail,
            coverage_pct=round(coverage_pct, 1),
            outcomes=outcomes,
        )
        logger.info(
            "batch_fetch_finished",
            success_count=success,
            failed_count=fail,
            duration_seconds=round(time.perf_counter() - batch_start, 2),
        )

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
            logger.debug("quote_cache_hit", ticker=ticker)
            return cached

        if getattr(settings, "ENABLE_REALTIME_SCRAPING", True):
            try:
                scraped_price = self.quote_provider.fetch_quote(ticker)
            except Exception as exc:
                scraped_price = None
                logger.warning(
                    "quote_scrape_failed",
                    ticker=ticker,
                    error_type=type(exc).__name__,
                )

            if scraped_price is not None:
                self._store_quote(ticker, float(scraped_price))
                logger.info("quote_scrape_succeeded", ticker=ticker)
                return float(scraped_price)

            provider_quote = self.provider.fetch_quote(ticker)
            if provider_quote is not None:
                self._store_quote(ticker, float(provider_quote))
                logger.info("quote_provider_succeeded", ticker=ticker)
                return float(provider_quote)

        df = self.fetch_single(ticker, period="5d", interval="1d")
        if df is not None and not df.empty:
            self._store_quote(ticker, float(df["close"].iloc[-1]))
            logger.info("quote_history_fallback_succeeded", ticker=ticker)
            return float(df["close"].iloc[-1])

        logger.error("quote_resolution_failed", ticker=ticker)
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
            logger.error("info_fetch_error", ticker=ticker, error=str(e))
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
                history_key
                for history_key in list(self._history_cache)
                if (normalized_ticker is None or history_key[0] == normalized_ticker)
                and (period is None or history_key[1] == period)
                and (interval is None or history_key[2] == interval)
                and (scope != "intraday_fetch" or self._is_intraday_interval(history_key[2]))
            ]
            for history_key in history_keys:
                self._history_cache.pop(history_key, None)

        if scope in {"all", "analysis"}:
            analysis_keys: list[str] = [
                analysis_key
                for analysis_key in list(self._analysis_cache)
                if normalized_ticker is None or analysis_key.startswith(f"{normalized_ticker}|")
            ]
            for analysis_key in analysis_keys:
                self._analysis_cache.pop(analysis_key, None)

        if scope in {"all", "quote_fallback"}:
            if normalized_ticker is None:
                self._quote_cache.clear()
            else:
                self._quote_cache.pop(normalized_ticker, None)

        logger.info("cache_cleared", scope=scope)

    def fetch_multi_timeframe_all(
        self,
        trend_period: str | None = None,
        trend_interval: str | None = None,
        trigger_period: str | None = None,
        trigger_interval: str | None = None,
        force_refresh: bool = False,
        validate: bool = True,
    ) -> dict[str, dict[str, pd.DataFrame]]:
        trend_period = trend_period or getattr(settings, "MTF_TREND_PERIOD", "6mo")
        trend_interval = trend_interval or getattr(settings, "MTF_TREND_INTERVAL", "1d")
        trigger_period = trigger_period or getattr(settings, "MTF_TRIGGER_PERIOD", "1mo")
        trigger_interval = trigger_interval or getattr(settings, "MTF_TRIGGER_INTERVAL", "15m")

        trend_data = self.fetch_all(
            period=trend_period, interval=trend_interval, force=force_refresh, validate=validate
        )
        trigger_data = self.fetch_all(
            period=trigger_period, interval=trigger_interval, force=force_refresh, validate=validate
        )

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
    "DataProviderRouter",
    "MarketDataProvider",
    "OfficialProvider",
    "OfficialProviderStub",
    "QuoteProvider",
    "RateLimiter",
    "YFinanceProvider",
    "_rate_limiter",
]
