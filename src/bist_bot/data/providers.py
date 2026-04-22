"""Provider adapters for market data and quote acquisition."""

from __future__ import annotations

import time
from abc import ABC
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.data import quotes as quote_helpers
from bist_bot.data.scraper import scrape_bist_quote

logger = get_logger(__name__, component="providers")


class RateLimiterProtocol(Protocol):
    def wait_if_needed(self, domain: str) -> None: ...


class MarketDataProvider(Protocol):
    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None: ...
    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]: ...
    def fetch_quote(self, ticker: str) -> float | None: ...
    def fetch_universe(self, force_refresh: bool = False) -> list[str]: ...


class QuoteProvider(Protocol):
    def fetch_quote(self, ticker: str) -> float | None: ...


class YFinanceProvider:
    def __init__(self, rate_limiter: RateLimiterProtocol) -> None:
        self.rate_limiter = rate_limiter

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        import yfinance as yf

        self.rate_limiter.wait_if_needed("yahoo.finance")
        stock = yf.Ticker(ticker)
        return stock.history(period=period, interval=interval)

    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]:
        import yfinance as yf

        if not tickers:
            return {}

        self.rate_limiter.wait_if_needed("yahoo.finance")
        raw_data = yf.download(
            tickers=" ".join(tickers),
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
        if raw_data is None or raw_data.empty:
            return {}

        results: dict[str, pd.DataFrame | None] = {}
        for ticker in tickers:
            try:
                if isinstance(raw_data.columns, pd.MultiIndex):
                    results[ticker] = raw_data[ticker].copy()
                else:
                    results[ticker] = raw_data.copy()
            except KeyError:
                results[ticker] = None
        return results

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

    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]:
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
    def authenticate(self, provider: "BaseOfficialProvider") -> str: ...
    def request(
        self,
        provider: "BaseOfficialProvider",
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
        super().__init__(f"Rate limited; retry after {retry_after}s" if retry_after else "Rate limited")


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

    def authenticate(self, provider: "BaseOfficialProvider") -> str:
        response = self.session.post(
            f"{provider.base_url}{provider.endpoints.auth}",
            json={"username": provider.username, "password": provider.password},
            headers={"X-API-Key": provider.api_key},
            timeout=provider.timeout,
        )
        body = self._parse_json(response)
        token = body.get("token") or body.get("access_token") or body.get("data", {}).get("token", "")
        if not token:
            raise AuthenticationError("No token in auth response")
        return str(token)

    def request(
        self,
        provider: "BaseOfficialProvider",
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
            raise BadResponseError(response.status_code, f"Unexpected payload type: {type(body).__name__}")
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
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        last_exc: OfficialProviderError | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._ensure_auth()
                return self._request(method, path, params=params, json_body=json_body)
            except RateLimitError as exc:
                wait = exc.retry_after or self.retry_backoff * (2 ** attempt)
                logger.warning("official_rate_limited", retry_after=wait, actionable_count=attempt)
                time.sleep(wait)
                last_exc = exc
            except BadResponseError as exc:
                if exc.status_code >= 500:
                    wait = self.retry_backoff * (2 ** attempt)
                    logger.warning("official_server_error_retry", error_type=str(exc.status_code), actionable_count=attempt)
                    time.sleep(wait)
                    last_exc = exc
                else:
                    raise
            except (ConnectionError, TimeoutError, OSError) as exc:
                wait = self.retry_backoff * (2 ** attempt)
                logger.warning("official_connection_retry", error_type=type(exc).__name__, actionable_count=attempt)
                time.sleep(wait)
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise OfficialProviderError("All retries exhausted")

    @staticmethod
    def _period_to_start_end(period: str) -> tuple[str, str]:
        now = datetime.now()
        mapping = {
            "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825,
            "1d": 1, "5d": 5, "ytd": None, "max": 3650,
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
            logger.exception("fetch_history failed for %s", ticker)
            return None
        records = resp.get("data", [])
        return self._ohlcv_from_records(records)

    def fetch_batch(self, tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame | None]:
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
            logger.exception("fetch_quote failed for %s", ticker)
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
        return resp.get("data", [])


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
