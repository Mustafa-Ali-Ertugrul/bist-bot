"""Provider adapters for market data and quote acquisition."""

from __future__ import annotations

import time
from abc import ABC
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import pandas as pd
import yfinance as yf

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.data import quotes as quote_helpers
from bist_bot.data.scraper import scrape_bist_quote

logger = get_logger(__name__, component="providers")


class RateLimiterProtocol(Protocol):
    def wait_if_needed(self, domain: str) -> None: ...


class MarketDataProvider(Protocol):
    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None: ...
    def fetch_batch(
        self, tickers: list[str], period: str, interval: str
    ) -> dict[str, pd.DataFrame | None]: ...
    def fetch_quote(self, ticker: str) -> float | None: ...
    def fetch_universe(self, force_refresh: bool = False) -> list[str]: ...


class QuoteProvider(Protocol):
    def fetch_quote(self, ticker: str) -> float | None: ...


class YFinanceProvider:
    def __init__(self, rate_limiter: RateLimiterProtocol) -> None:
        self.rate_limiter = rate_limiter

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if isinstance(exc, ConnectionError | TimeoutError | OSError):
            return True
        retryable_names = {"YFRateLimitError", "YFDownloadError", "YFTickerError"}
        return type(exc).__name__ in retryable_names

    def _retry_yfinance_call(self, func, ticker: str, *args, **kwargs) -> Any:
        max_retries = settings.data.YFINANCE_MAX_RETRIES
        backoff = settings.data.YFINANCE_RETRY_BACKOFF_SECONDS
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                self.rate_limiter.wait_if_needed("yahoo.finance")
                result = func(*args, **kwargs)
                if result is None or (isinstance(result, pd.DataFrame) and result.empty):
                    if attempt < max_retries:
                        logger.warning(
                            "yfinance_retry",
                            ticker=ticker,
                            attempt=attempt,
                            max_retries=max_retries,
                            error_type="empty_response",
                            final_result="retrying",
                        )
                        time.sleep(backoff * (2 ** (attempt - 1)))
                        continue
                logger.info(
                    "yfinance_fetch_success",
                    ticker=ticker,
                    attempt=attempt,
                    max_retries=max_retries,
                    final_result="success",
                )
                return result
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "yfinance_retry",
                        ticker=ticker,
                        attempt=attempt,
                        max_retries=max_retries,
                        error_type=type(exc).__name__,
                        final_result="retrying",
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    "yfinance_fetch_failed",
                    ticker=ticker,
                    attempt=attempt,
                    max_retries=max_retries,
                    error_type=type(exc).__name__,
                    final_result="failure",
                )
                return None
            except Exception as exc:
                if self._is_retryable_error(exc):
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff * (2 ** (attempt - 1))
                        logger.warning(
                            "yfinance_retry",
                            ticker=ticker,
                            attempt=attempt,
                            max_retries=max_retries,
                            error_type=type(exc).__name__,
                            final_result="retrying",
                        )
                        time.sleep(wait)
                        continue
                logger.error(
                    "yfinance_fetch_failed",
                    ticker=ticker,
                    attempt=attempt,
                    max_retries=max_retries,
                    error_type=type(exc).__name__,
                    final_result="failure",
                )
                return None
        if last_exc is not None:
            logger.error(
                "yfinance_fetch_exhausted",
                ticker=ticker,
                max_retries=max_retries,
                final_result="failure",
            )
        return None

    def _fetch_chart_history(
        self, ticker: str, period: str, interval: str, *, rate_limit: bool = True
    ) -> pd.DataFrame | None:
        import requests

        if rate_limit:
            self.rate_limiter.wait_if_needed("yahoo.finance")
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": period, "interval": interval},
            timeout=6,
        )
        response.raise_for_status()
        payload = response.json()
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        if not timestamps or not quote:
            return None
        df = pd.DataFrame(
            {
                "Open": quote.get("open", []),
                "High": quote.get("high", []),
                "Low": quote.get("low", []),
                "Close": quote.get("close", []),
                "Volume": quote.get("volume", []),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None),
        )
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return None if df.empty else df

    def _fetch_stockanalysis_history(self, ticker: str) -> pd.DataFrame | None:
        """Fetch daily BIST OHLCV data from StockAnalysis when Yahoo is rate-limited."""
        import requests
        from bs4 import BeautifulSoup

        symbol = ticker.upper().replace(".IS", "")
        response = requests.get(
            f"https://stockanalysis.com/quote/ist/{symbol}/history/",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if table is None:
            return None
        headers = [cell.get_text(strip=True) for cell in table.find_all("th")]
        required = ["Date", "Open", "High", "Low", "Close", "Volume"]
        if not all(column in headers for column in required):
            return None
        indexes = {column: headers.index(column) for column in required}
        records: list[dict[str, str]] = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(strip=True).replace(",", "") for cell in row.find_all("td")]
            if len(cells) < len(headers):
                continue
            records.append({column: cells[indexes[column]] for column in required})
        if not records:
            return None
        df = pd.DataFrame.from_records(records)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        for column in ["Open", "High", "Low", "Close", "Volume"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df.dropna(subset=["Date", "Open", "High", "Low", "Close", "Volume"])
        if df.empty:
            return None
        return df.sort_values("Date").set_index("Date")

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        if ticker.upper().endswith(".IS"):
            try:
                chart_history = self._fetch_chart_history(ticker, period, interval)
                if chart_history is not None:
                    return chart_history
            except Exception:
                logger.warning("yahoo_chart_history_failed", ticker=ticker)

        def _fetch():
            stock = yf.Ticker(ticker)
            try:
                return stock.history(period=period, interval=interval, timeout=12)
            except TypeError:
                return stock.history(period=period, interval=interval)

        result = self._retry_yfinance_call(_fetch, ticker)
        if result is not None and not result.empty:
            return result

        if ticker.upper().endswith(".IS"):
            try:
                chart_history = self._fetch_chart_history(ticker, period, interval)
                if chart_history is not None:
                    return chart_history
            except Exception:
                logger.warning("yahoo_chart_history_fallback_failed", ticker=ticker)
            return self._fetch_stockanalysis_history(ticker)
        return None

    def fetch_batch(
        self, tickers: list[str], period: str, interval: str
    ) -> dict[str, pd.DataFrame | None]:
        if not tickers:
            return {}

        if all(ticker.upper().endswith(".IS") for ticker in tickers):
            with ThreadPoolExecutor(max_workers=min(6, len(tickers))) as executor:
                future_map = {
                    executor.submit(
                        self._fetch_chart_history,
                        ticker,
                        period,
                        interval,
                        rate_limit=False,
                    ): ticker
                    for ticker in tickers
                }
                results: dict[str, pd.DataFrame | None] = {}
                for future in as_completed(future_map):
                    ticker = future_map[future]
                    try:
                        results[ticker] = future.result()
                    except Exception:
                        results[ticker] = None
                    if results[ticker] is None:
                        try:
                            results[ticker] = self._fetch_stockanalysis_history(ticker)
                        except Exception:
                            results[ticker] = None
                return results

        max_retries = settings.data.YFINANCE_MAX_RETRIES
        backoff = settings.data.YFINANCE_RETRY_BACKOFF_SECONDS
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                self.rate_limiter.wait_if_needed("yahoo.finance")
                raw_data = yf.download(
                    tickers=" ".join(tickers),
                    period=period,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                    timeout=getattr(settings.data, "PROVIDER_BATCH_TIMEOUT_SECONDS", 60),
                )
                if raw_data is None or (isinstance(raw_data, pd.DataFrame) and raw_data.empty):
                    if attempt < max_retries:
                        logger.warning(
                            "yfinance_batch_retry",
                            ticker_count=len(tickers),
                            attempt=attempt,
                            max_retries=max_retries,
                            error_type="empty_response",
                            final_result="retrying",
                        )
                        time.sleep(backoff * (2 ** (attempt - 1)))
                        continue
                    logger.warning("yfinance_batch_empty", ticker_count=len(tickers))
                    return {}
                logger.info(
                    "yfinance_batch_success",
                    ticker_count=len(tickers),
                    attempt=attempt,
                    max_retries=max_retries,
                    final_result="success",
                )
                results: dict[str, pd.DataFrame | None] = {}
                for ticker in tickers:
                    try:
                        if isinstance(raw_data.columns, pd.MultiIndex):
                            results[ticker] = raw_data[ticker].copy()
                        else:
                            results[ticker] = raw_data.copy()
                    except KeyError:
                        logger.warning("yfinance_batch_missing_ticker", ticker=ticker)
                        results[ticker] = None
                return results
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "yfinance_batch_retry",
                        ticker_count=len(tickers),
                        attempt=attempt,
                        max_retries=max_retries,
                        error_type=type(exc).__name__,
                        final_result="retrying",
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    "yfinance_batch_failed",
                    ticker_count=len(tickers),
                    attempt=attempt,
                    max_retries=max_retries,
                    error_type=type(exc).__name__,
                    final_result="failure",
                )
                return {}
            except Exception as exc:
                if self._is_retryable_error(exc):
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff * (2 ** (attempt - 1))
                        logger.warning(
                            "yfinance_batch_retry",
                            ticker_count=len(tickers),
                            attempt=attempt,
                            max_retries=max_retries,
                            error_type=type(exc).__name__,
                            final_result="retrying",
                        )
                        time.sleep(wait)
                        continue
                logger.error(
                    "yfinance_batch_failed",
                    ticker_count=len(tickers),
                    attempt=attempt,
                    max_retries=max_retries,
                    error_type=type(exc).__name__,
                    final_result="failure",
                )
                return {}
        if last_exc is not None:
            logger.error("yfinance_batch_exhausted", ticker_count=len(tickers))
            return {}
        return {}

    def fetch_quote(self, ticker: str) -> float | None:
        _ = ticker
        return None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        return quote_helpers.get_bist100_tickers(self.rate_limiter, force_refresh=force_refresh)


class BorsaIstanbulQuoteProvider:
    def __init__(self, rate_limiter: RateLimiterProtocol) -> None:
        self.rate_limiter = rate_limiter

    def fetch_quote(self, ticker: str) -> float | None:
        result = scrape_bist_quote(ticker, self.rate_limiter)
        if result.success and result.price is not None:
            return float(result.price)
        return None


class OfficialProviderStub:
    """Placeholder adapter for use in tests and as a fallback stub."""

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        _ = ticker, period, interval
        return None

    def fetch_batch(
        self, tickers: list[str], period: str, interval: str
    ) -> dict[str, pd.DataFrame | None]:
        _ = period, interval
        return {ticker: None for ticker in tickers}

    def fetch_quote(self, ticker: str) -> float | None:
        _ = ticker
        return None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        _ = force_refresh
        return []


@dataclass
class OfficialProviderEndpoints:
    """Configurable REST endpoint mapping for an official data provider.

    Subclass or override fields to adapt to Matriks, Foreks, Finnet, etc.
    """

    auth: str = "/api/auth/token"
    history: str = "/api/data/history"
    batch: str = "/api/data/batch"
    quote: str = "/api/data/quote"
    universe: str = "/api/data/universe"


class OfficialHTTPClientProtocol(Protocol):
    def authenticate(self, provider: BaseOfficialProvider) -> str: ...
    def request(
        self,
        provider: BaseOfficialProvider,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class OfficialProviderError(Exception):
    """Base exception for official provider errors."""


class AuthenticationError(OfficialProviderError):
    """Raised when authentication with the official provider fails."""


class RateLimitError(OfficialProviderError):
    """Raised when the official provider rate-limits requests."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Rate limited; retry after {retry_after}s" if retry_after else "Rate limited"
        )


class BadResponseError(OfficialProviderError):
    """Raised when the official provider returns an unexpected response."""

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Bad response {status_code}: {body[:200]}")


class RequestsOfficialHTTPClient:
    """Generic requests-based HTTP client for official providers."""

    def __init__(self, session: Any | None = None) -> None:
        if session is not None:
            self.session = session
            return
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - dependency should exist in runtime
            raise RuntimeError("requests library is required for OfficialProvider") from exc
        self.session = requests.Session()

    def authenticate(self, provider: BaseOfficialProvider) -> str:
        response = self.session.post(
            f"{provider.base_url}{provider.endpoints.auth}",
            json={"username": provider.username, "password": provider.password},
            headers={"X-API-Key": provider.api_key},
            timeout=provider.timeout,
        )
        body = self._parse_json(response)
        token = (
            body.get("token") or body.get("access_token") or body.get("data", {}).get("token", "")
        )
        if not token:
            raise AuthenticationError("No token in auth response")
        return str(token)

    def request(
        self,
        provider: BaseOfficialProvider,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{provider.base_url}{path}",
            headers={
                "Authorization": f"Bearer {provider._session_token}",
                "X-API-Key": provider.api_key,
                "Accept": "application/json",
            },
            params=params,
            json=json_body,
            timeout=provider.timeout,
        )
        return self._parse_json(response, clear_auth=lambda: provider._clear_auth())

    def _parse_json(self, response: Any, clear_auth: Any | None = None) -> dict[str, Any]:
        if response.status_code == 401:
            if clear_auth is not None:
                clear_auth()
            raise AuthenticationError(f"Authentication failed: {response.text[:200]}")
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 0) or 0) or None
            raise RateLimitError(retry_after=retry_after)
        if response.status_code >= 400:
            raise BadResponseError(response.status_code, response.text)
        try:
            body = response.json()
        except Exception as exc:
            raise BadResponseError(response.status_code, f"Invalid JSON response: {exc}") from exc
        if not isinstance(body, dict):
            raise BadResponseError(
                response.status_code, f"Unexpected payload type: {type(body).__name__}"
            )
        return body


class BaseOfficialProvider(ABC):
    """Abstract base for official/paid data provider adapters.

    Subclass this to integrate Matriks, Foreks, Finnet or any
    vendor-specific REST API.  Override :attr:`endpoints` and
    the HTTP-layer hooks as needed.
    """

    endpoints: OfficialProviderEndpoints = OfficialProviderEndpoints()

    def __init__(
        self,
        base_url: str,
        api_key: str,
        username: str,
        password: str,
        *,
        rate_limiter: RateLimiterProtocol | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        http_client: OfficialHTTPClientProtocol | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.username = username
        self.password = password
        self.rate_limiter = rate_limiter
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.http_client = http_client or RequestsOfficialHTTPClient()
        self._session_token: str | None = None
        self._token_expires: datetime | None = None

    def _clear_auth(self) -> None:
        self._session_token = None
        self._token_expires = None

    def _authenticate(self) -> str:
        return self.http_client.authenticate(self)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.http_client.request(self, method, path, params=params, json_body=json_body)

    def _ensure_auth(self) -> None:
        if self._session_token and self._token_expires and datetime.now() < self._token_expires:
            return
        self._session_token = self._authenticate()
        self._token_expires = datetime.now() + timedelta(hours=1)

    def _wait_rate_limit(self) -> None:
        if self.rate_limiter is not None:
            self.rate_limiter.wait_if_needed("official.provider")

    def _retry_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._ensure_auth()
                return self._request(method, path, params=params, json_body=json_body)
            except RateLimitError as exc:
                wait = exc.retry_after or self.retry_backoff * (2**attempt)
                logger.warning("official_rate_limited", retry_after=wait, actionable_count=attempt)
                time.sleep(wait)
                last_exc = exc
            except BadResponseError as exc:
                if exc.status_code >= 500:
                    wait = self.retry_backoff * (2**attempt)
                    logger.warning(
                        "official_server_error_retry",
                        error_type=str(exc.status_code),
                        actionable_count=attempt,
                    )
                    time.sleep(wait)
                    last_exc = exc
                else:
                    raise
            except (ConnectionError, TimeoutError, OSError) as exc:
                wait = self.retry_backoff * (2**attempt)
                logger.warning(
                    "official_connection_retry",
                    error_type=type(exc).__name__,
                    actionable_count=attempt,
                )
                time.sleep(wait)
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise OfficialProviderError("All retries exhausted")

    @staticmethod
    def _period_to_start_end(period: str) -> tuple[str, str]:
        now = datetime.now()
        mapping = {
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 730,
            "5y": 1825,
            "1d": 1,
            "5d": 5,
            "ytd": None,
            "max": 3650,
        }
        days = mapping.get(period, 90)
        if period == "ytd":
            start = datetime(now.year, 1, 1)
        else:
            start = now - timedelta(days=days or 90)
        return start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    @staticmethod
    def _ohlcv_from_records(records: list[dict]) -> pd.DataFrame | None:
        if not records:
            return None
        df = pd.DataFrame(records)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
        col_map = {c: c.lower() for c in df.columns}
        df.rename(columns=col_map, inplace=True)
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            return None
        return df[sorted(required)]

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        self._wait_rate_limit()
        start_date, end_date = self._period_to_start_end(period)
        try:
            resp = self._retry_request(
                "GET",
                self.endpoints.history,
                params={
                    "ticker": ticker,
                    "startDate": start_date,
                    "endDate": end_date,
                    "interval": interval,
                },
            )
        except OfficialProviderError:
            logger.exception("fetch_history_failed", ticker=ticker)
            return None
        records = resp.get("data", [])
        return self._ohlcv_from_records(records)

    def fetch_batch(
        self, tickers: list[str], period: str, interval: str
    ) -> dict[str, pd.DataFrame | None]:
        if not tickers:
            return {}
        self._wait_rate_limit()
        start_date, end_date = self._period_to_start_end(period)
        try:
            resp = self._retry_request(
                "POST",
                self.endpoints.batch,
                json_body={
                    "tickers": tickers,
                    "startDate": start_date,
                    "endDate": end_date,
                    "interval": interval,
                },
            )
        except OfficialProviderError:
            logger.exception("fetch_batch failed")
            return {t: None for t in tickers}
        items = resp.get("data", {})
        results: dict[str, pd.DataFrame | None] = {}
        for ticker in tickers:
            records = items.get(ticker, [])
            if not records:
                logger.info("official_batch_missing_ticker", ticker=ticker)
            results[ticker] = self._ohlcv_from_records(records)
        return results

    def fetch_quote(self, ticker: str) -> float | None:
        self._wait_rate_limit()
        try:
            resp = self._retry_request(
                "GET",
                self.endpoints.quote,
                params={"ticker": ticker},
            )
        except OfficialProviderError:
            logger.exception("fetch_quote_failed", ticker=ticker)
            return None
        price = resp.get("data", {}).get("price")
        return float(price) if price is not None else None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        _ = force_refresh
        self._wait_rate_limit()
        try:
            resp = self._retry_request("GET", self.endpoints.universe)
        except OfficialProviderError:
            logger.exception("fetch_universe failed")
            return []
        data = resp.get("data", [])
        if isinstance(data, list):
            return [str(item) for item in data]
        return []


class OfficialProvider(BaseOfficialProvider):
    """Config-driven generic REST adapter for official data providers.

    Uses ``requests`` for HTTP communication.  Endpoint paths are
    overridable via :attr:`endpoints` so Matriks / Foreks / Finnet
    sub-classes only need to override the endpoint mapping and any
    vendor-specific request/response transforms.

    Example::

        class MatriksProvider(OfficialProvider):
            endpoints = OfficialProviderEndpoints(
                auth="/matriks/v1/auth",
                history="/matriks/v1/ohlcv",
                batch="/matriks/v1/ohlcv/batch",
                quote="/matriks/v1/quote",
                universe="/matriks/v1/symbols",
            )
    """

    pass


class MatriksProvider(OfficialProvider):
    endpoints = OfficialProviderEndpoints(
        auth="/matriks/v1/auth",
        history="/matriks/v1/ohlcv",
        batch="/matriks/v1/ohlcv/batch",
        quote="/matriks/v1/quote",
        universe="/matriks/v1/symbols",
    )


class ForeksProvider(OfficialProvider):
    endpoints = OfficialProviderEndpoints(
        auth="/foreks/v1/auth",
        history="/foreks/v1/history",
        batch="/foreks/v1/history/batch",
        quote="/foreks/v1/quote",
        universe="/foreks/v1/symbols",
    )


class FinnetProvider(OfficialProvider):
    endpoints = OfficialProviderEndpoints(
        auth="/finnet/v1/auth",
        history="/finnet/v1/history",
        batch="/finnet/v1/history/batch",
        quote="/finnet/v1/quote",
        universe="/finnet/v1/symbols",
    )


def resolve_official_endpoints(
    *,
    vendor: str = "generic",
    auth: str | None = None,
    history: str | None = None,
    batch: str | None = None,
    quote: str | None = None,
    universe: str | None = None,
) -> OfficialProviderEndpoints:
    provider_map = {
        "generic": OfficialProvider,
        "matriks": MatriksProvider,
        "foreks": ForeksProvider,
        "finnet": FinnetProvider,
    }
    base_endpoints = provider_map.get(vendor.lower(), OfficialProvider).endpoints
    return OfficialProviderEndpoints(
        auth=auth or base_endpoints.auth,
        history=history or base_endpoints.history,
        batch=batch or base_endpoints.batch,
        quote=quote or base_endpoints.quote,
        universe=universe or base_endpoints.universe,
    )


def build_official_provider(
    *,
    vendor: str,
    base_url: str,
    api_key: str,
    username: str,
    password: str,
    rate_limiter: RateLimiterProtocol | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    retry_backoff: float = 1.0,
    http_client: OfficialHTTPClientProtocol | None = None,
    endpoints: OfficialProviderEndpoints | None = None,
) -> OfficialProvider:
    provider_cls = {
        "generic": OfficialProvider,
        "matriks": MatriksProvider,
        "foreks": ForeksProvider,
        "finnet": FinnetProvider,
    }.get(vendor.lower(), OfficialProvider)
    provider = provider_cls(
        base_url=base_url,
        api_key=api_key,
        username=username,
        password=password,
        rate_limiter=rate_limiter,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        http_client=http_client,
    )
    if endpoints is not None:
        provider.endpoints = endpoints
    return provider


@dataclass
class _ProviderHealth:
    consecutive_failures: int = 0
    last_failure_time: float = 0.0


class DataProviderRouter:
    """Failover router that tries providers in order with circuit-breaker logic."""

    def __init__(
        self,
        providers: list[MarketDataProvider],
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if not providers:
            raise ValueError("At least one provider required")
        self._providers = providers
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._health: dict[int, _ProviderHealth] = {
            i: _ProviderHealth() for i in range(len(providers))
        }

    def _is_available(self, idx: int) -> bool:
        h = self._health[idx]
        if h.consecutive_failures < self._failure_threshold:
            return True
        elapsed = time.monotonic() - h.last_failure_time
        return elapsed >= self._cooldown_seconds

    def _record_success(self, idx: int) -> None:
        self._health[idx].consecutive_failures = 0

    def _record_failure(self, idx: int) -> None:
        h = self._health[idx]
        h.consecutive_failures += 1
        h.last_failure_time = time.monotonic()

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        for idx, provider in enumerate(self._providers):
            if not self._is_available(idx):
                continue
            try:
                result = provider.fetch_history(ticker, period, interval)
                if result is not None:
                    self._record_success(idx)
                    return result
                logger.info(
                    "provider_returned_none",
                    provider_index=idx,
                    provider_type=type(provider).__name__,
                    ticker=ticker,
                    method="fetch_history",
                )
            except Exception:
                self._record_failure(idx)
                logger.warning("provider_failover", provider_index=idx, ticker=ticker)
        return None

    def fetch_batch(
        self, tickers: list[str], period: str, interval: str
    ) -> dict[str, pd.DataFrame | None]:
        for idx, provider in enumerate(self._providers):
            if not self._is_available(idx):
                continue
            try:
                result = provider.fetch_batch(tickers, period, interval)
                if result is None:
                    logger.info(
                        "provider_batch_returned_none",
                        provider_index=idx,
                        provider_type=type(provider).__name__,
                        ticker_count=len(tickers),
                    )
                    continue
                self._record_success(idx)
                none_tickers = [t for t in tickers if result.get(t) is None]
                if none_tickers:
                    logger.info(
                        "provider_batch_partial_none",
                        provider_index=idx,
                        provider_type=type(provider).__name__,
                        none_count=len(none_tickers),
                        none_tickers=none_tickers[:20],
                    )
                return result
            except Exception:
                self._record_failure(idx)
                logger.warning("provider_failover_batch", provider_index=idx)
        return self._providers[-1].fetch_batch(tickers, period, interval)

    def fetch_quote(self, ticker: str) -> float | None:
        for idx, provider in enumerate(self._providers):
            if not self._is_available(idx):
                continue
            try:
                result = provider.fetch_quote(ticker)
                if result is not None:
                    self._record_success(idx)
                    return result
                logger.info(
                    "provider_returned_none",
                    provider_index=idx,
                    provider_type=type(provider).__name__,
                    ticker=ticker,
                    method="fetch_quote",
                )
            except Exception:
                self._record_failure(idx)
        return None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        for idx, provider in enumerate(self._providers):
            if not self._is_available(idx):
                continue
            try:
                result = provider.fetch_universe(force_refresh=force_refresh)
                self._record_success(idx)
                return result
            except Exception:
                self._record_failure(idx)
        return self._providers[-1].fetch_universe(force_refresh=force_refresh)
