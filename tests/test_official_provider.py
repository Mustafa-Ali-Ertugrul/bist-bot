"""Tests for OfficialProvider adapter: auth, fetch_history, fetch_quote, error handling, and fallback."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bist_bot.data.providers import (
    AuthenticationError,
    BadResponseError,
    FinnetProvider,
    ForeksProvider,
    MatriksProvider,
    OfficialProvider,
    OfficialProviderEndpoints,
    OfficialProviderStub,
    RateLimitError,
    RequestsOfficialHTTPClient,
    build_official_provider,
    resolve_official_endpoints,
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_body: dict | None = None,
        text: str = "",
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


class _FakeRateLimiter:
    def __init__(self):
        self.calls: list[str] = []

    def wait_if_needed(self, domain: str) -> None:
        self.calls.append(domain)


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse] | None = None):
        self.responses = responses or []
        self.calls: list[tuple[str, str, dict]] = []

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _make_provider(**overrides) -> OfficialProvider:
    defaults = dict(
        base_url="https://api.example.com",
        api_key="test-key",
        username="user",
        password="pass",
        max_retries=2,
        retry_backoff=0.01,
        http_client=RequestsOfficialHTTPClient(session=_FakeSession()),
    )
    defaults.update(overrides)
    return OfficialProvider(**defaults)


class TestOfficialProviderAuth:
    def test_auth_success_stores_token(self):
        provider = _make_provider(
            http_client=RequestsOfficialHTTPClient(
                session=_FakeSession([_FakeResponse(200, {"token": "abc123"})])
            )
        )
        token = provider._authenticate()
        assert token == "abc123"

    def test_auth_success_access_token_field(self):
        provider = _make_provider(
            http_client=RequestsOfficialHTTPClient(
                session=_FakeSession([_FakeResponse(200, {"access_token": "xyz"})])
            )
        )
        assert provider._authenticate() == "xyz"

    def test_auth_success_nested_data_token(self):
        provider = _make_provider(
            http_client=RequestsOfficialHTTPClient(
                session=_FakeSession([_FakeResponse(200, {"data": {"token": "nested-tok"}})])
            )
        )
        assert provider._authenticate() == "nested-tok"

    def test_auth_401_raises_authentication_error(self):
        provider = _make_provider(
            http_client=RequestsOfficialHTTPClient(
                session=_FakeSession([_FakeResponse(401, text="Unauthorized")])
            )
        )
        with pytest.raises(AuthenticationError, match="Authentication failed"):
            provider._authenticate()

    def test_auth_no_token_in_response_raises(self):
        provider = _make_provider(
            http_client=RequestsOfficialHTTPClient(
                session=_FakeSession([_FakeResponse(200, {"message": "ok"})])
            )
        )
        with pytest.raises(AuthenticationError, match="No token"):
            provider._authenticate()

    def test_auth_429_raises_rate_limit_error(self):
        provider = _make_provider(
            http_client=RequestsOfficialHTTPClient(
                session=_FakeSession([_FakeResponse(429, headers={"Retry-After": "5"})])
            )
        )
        with pytest.raises(RateLimitError) as exc_info:
            provider._authenticate()
        assert exc_info.value.retry_after == 5.0

    def test_ensure_auth_skips_when_token_valid(self):
        provider = _make_provider()
        provider._session_token = "existing"
        provider._token_expires = datetime(2099, 1, 1)
        provider._authenticate = MagicMock()
        provider._ensure_auth()
        provider._authenticate.assert_not_called()

    def test_ensure_auth_calls_when_token_missing(self):
        provider = _make_provider()
        provider._session_token = None
        provider._authenticate = MagicMock(return_value="new-token")
        provider._ensure_auth()
        provider._authenticate.assert_called_once()
        assert provider._session_token == "new-token"


class TestOfficialProviderFetchHistory:
    @pytest.fixture()
    def authenticated_provider(self):
        provider = _make_provider(http_client=RequestsOfficialHTTPClient(session=_FakeSession()))
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        return provider

    def test_fetch_history_returns_dataframe(self, authenticated_provider):
        ohlcv_data = [
            {
                "date": "2025-01-01",
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 102,
                "volume": 1000,
            },
            {
                "date": "2025-01-02",
                "open": 102,
                "high": 108,
                "low": 101,
                "close": 106,
                "volume": 1200,
            },
        ]
        authenticated_provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": ohlcv_data})])
        )
        df = authenticated_provider.fetch_history("THYAO.IS", "3mo", "1d")
        assert df is not None
        assert "close" in df.columns
        assert len(df) == 2

    def test_fetch_history_empty_data_returns_none(self, authenticated_provider):
        authenticated_provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": []})])
        )
        df = authenticated_provider.fetch_history("THYAO.IS", "3mo", "1d")
        assert df is None

    def test_fetch_history_error_returns_none(self, authenticated_provider):
        authenticated_provider._request = MagicMock(side_effect=BadResponseError(500, "boom"))
        df = authenticated_provider.fetch_history("THYAO.IS", "3mo", "1d")
        assert df is None

    def test_fetch_history_calls_rate_limiter(self):
        limiter = _FakeRateLimiter()
        provider = _make_provider(rate_limiter=limiter)
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": []})])
        )
        provider.fetch_history("THYAO.IS", "3mo", "1d")
        assert "official.provider" in limiter.calls


class TestOfficialProviderFetchQuote:
    @pytest.fixture()
    def authenticated_provider(self):
        provider = _make_provider(http_client=RequestsOfficialHTTPClient(session=_FakeSession()))
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        return provider

    def test_fetch_quote_returns_price(self, authenticated_provider):
        authenticated_provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": {"price": 152.50}})])
        )
        price = authenticated_provider.fetch_quote("THYAO.IS")
        assert price == 152.50

    def test_fetch_quote_missing_price_returns_none(self, authenticated_provider):
        authenticated_provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": {}})])
        )
        price = authenticated_provider.fetch_quote("THYAO.IS")
        assert price is None

    def test_fetch_quote_error_returns_none(self, authenticated_provider):
        authenticated_provider._request = MagicMock(side_effect=BadResponseError(500, "boom"))
        price = authenticated_provider.fetch_quote("THYAO.IS")
        assert price is None


class TestOfficialProviderFetchBatch:
    @pytest.fixture()
    def authenticated_provider(self):
        provider = _make_provider(http_client=RequestsOfficialHTTPClient(session=_FakeSession()))
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        return provider

    def test_fetch_batch_returns_results(self, authenticated_provider):
        batch_data = {
            "THYAO.IS": [
                {
                    "date": "2025-01-01",
                    "open": 100,
                    "high": 105,
                    "low": 98,
                    "close": 102,
                    "volume": 1000,
                }
            ],
            "ASELS.IS": [
                {
                    "date": "2025-01-01",
                    "open": 50,
                    "high": 52,
                    "low": 49,
                    "close": 51,
                    "volume": 500,
                }
            ],
        }
        authenticated_provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": batch_data})])
        )
        results = authenticated_provider.fetch_batch(["THYAO.IS", "ASELS.IS"], "3mo", "1d")
        assert results["THYAO.IS"] is not None
        assert results["ASELS.IS"] is not None

    def test_fetch_batch_empty_tickers_returns_empty(self, authenticated_provider):
        results = authenticated_provider.fetch_batch([], "3mo", "1d")
        assert results == {}

    def test_fetch_batch_error_returns_nones(self, authenticated_provider):
        authenticated_provider._request = MagicMock(side_effect=BadResponseError(500, "boom"))
        results = authenticated_provider.fetch_batch(["THYAO.IS"], "3mo", "1d")
        assert results["THYAO.IS"] is None


class TestOfficialProviderFetchUniverse:
    @pytest.fixture()
    def authenticated_provider(self):
        provider = _make_provider(http_client=RequestsOfficialHTTPClient(session=_FakeSession()))
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        return provider

    def test_fetch_universe_returns_list(self, authenticated_provider):
        authenticated_provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(200, {"data": ["THYAO.IS", "ASELS.IS"]})])
        )
        universe = authenticated_provider.fetch_universe()
        assert universe == ["THYAO.IS", "ASELS.IS"]

    def test_fetch_universe_error_returns_empty(self, authenticated_provider):
        authenticated_provider._request = MagicMock(side_effect=BadResponseError(500, "boom"))
        universe = authenticated_provider.fetch_universe()
        assert universe == []


class TestOfficialProviderRetry:
    def test_retries_on_server_error(self):
        provider = _make_provider(max_retries=3, retry_backoff=0.01)
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider._request = MagicMock(
            side_effect=[
                BadResponseError(503, "temporarily unavailable"),
                BadResponseError(503, "temporarily unavailable"),
                {"data": []},
            ]
        )

        provider._retry_request("GET", "/api/test")

    def test_retries_on_rate_limit(self):
        provider = _make_provider()
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider._request = MagicMock(side_effect=[RateLimitError(retry_after=0.01), {"data": []}])

        provider._retry_request("GET", "/api/test")

    def test_raises_after_max_retries(self):
        provider = _make_provider(max_retries=2, retry_backoff=0.01)
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider._request = MagicMock(side_effect=BadResponseError(503, "down"))
        with pytest.raises(BadResponseError, match="503"):
            provider._retry_request("GET", "/api/test")

    def test_client_error_not_retried(self):
        provider = _make_provider()
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider._request = MagicMock(side_effect=BadResponseError(400, "bad request"))
        with pytest.raises(BadResponseError, match="400"):
            provider._retry_request("GET", "/api/test")

    def test_retries_on_connection_error(self):
        provider = _make_provider()
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider._request = MagicMock(side_effect=[ConnectionError("refused"), {"data": []}])

        provider._retry_request("GET", "/api/test")

    def test_401_in_request_clears_token(self):
        provider = _make_provider()
        provider._session_token = "tok"
        provider._token_expires = datetime(2099, 1, 1)
        provider.http_client = RequestsOfficialHTTPClient(
            session=_FakeSession([_FakeResponse(401, text="expired")])
        )
        with pytest.raises(AuthenticationError):
            provider._request("GET", "/api/test")
        assert provider._session_token is None
        assert provider._token_expires is None


class TestOfficialProviderPeriodMapping:
    def test_period_to_start_end(self):
        start, end = OfficialProvider._period_to_start_end("3mo")
        assert start < end

    def test_period_ytd(self):
        start, _end = OfficialProvider._period_to_start_end("ytd")
        assert start.startswith(str(datetime.now().year))

    def test_period_unknown_defaults(self):
        start, end = OfficialProvider._period_to_start_end("unknown")
        assert start < end


class TestOfficialProviderOHLCVParsing:
    def test_ohlcv_from_records_valid(self):
        records = [
            {
                "date": "2025-01-01",
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 102,
                "volume": 1000,
            },
        ]
        df = OfficialProvider._ohlcv_from_records(records)
        assert df is not None
        assert "close" in df.columns

    def test_ohlcv_from_records_empty(self):
        assert OfficialProvider._ohlcv_from_records([]) is None

    def test_ohlcv_from_records_missing_columns(self):
        records = [{"date": "2025-01-01", "close": 102}]
        assert OfficialProvider._ohlcv_from_records(records) is None


class TestOfficialProviderEndpoints:
    def test_default_endpoints(self):
        ep = OfficialProviderEndpoints()
        assert ep.auth == "/api/auth/token"
        assert ep.history == "/api/data/history"

    def test_custom_endpoints(self):
        ep = OfficialProviderEndpoints(auth="/v2/login", history="/v2/ohlcv")
        assert ep.auth == "/v2/login"

    def test_subclass_overrides_endpoints(self):
        provider = MatriksProvider(
            base_url="https://api.matriks.com",
            api_key="k",
            username="u",
            password="p",
            http_client=RequestsOfficialHTTPClient(session=_FakeSession()),
        )
        assert provider.endpoints.auth == "/matriks/v1/auth"
        assert provider.endpoints.history == "/matriks/v1/ohlcv"
        assert provider.endpoints.quote == "/matriks/v1/quote"

    def test_resolve_official_endpoints_supports_vendor_and_overrides(self):
        endpoints = resolve_official_endpoints(vendor="foreks", quote="/custom/quote")

        assert endpoints.auth == ForeksProvider.endpoints.auth
        assert endpoints.quote == "/custom/quote"

    def test_build_official_provider_creates_vendor_specific_adapter(self):
        provider = build_official_provider(
            vendor="finnet",
            base_url="https://api.finnet.example",
            api_key="k",
            username="u",
            password="p",
            http_client=RequestsOfficialHTTPClient(session=_FakeSession()),
        )

        assert isinstance(provider, FinnetProvider)


class TestOfficialProviderStub:
    def test_stub_fetch_history_returns_none(self):
        stub = OfficialProviderStub()
        assert stub.fetch_history("X", "3mo", "1d") is None

    def test_stub_fetch_batch_returns_nones(self):
        stub = OfficialProviderStub()
        result = stub.fetch_batch(["A", "B"], "3mo", "1d")
        assert result == {"A": None, "B": None}

    def test_stub_fetch_quote_returns_none(self):
        stub = OfficialProviderStub()
        assert stub.fetch_quote("X") is None

    def test_stub_fetch_universe_returns_empty(self):
        stub = OfficialProviderStub()
        assert stub.fetch_universe() == []


class TestDependenciesDataProviderSelection:
    def test_official_provider_selected(self):
        from bist_bot.config.settings import settings
        from bist_bot.dependencies import _build_data_provider

        with settings.override(
            DATA_PROVIDER="official",
            OFFICIAL_VENDOR="matriks",
            OFFICIAL_API_BASE_URL="https://api.example.com",
            OFFICIAL_API_KEY="key",
            OFFICIAL_USERNAME="user",
            OFFICIAL_PASSWORD="pass",
        ):
            provider = _build_data_provider()
        assert isinstance(provider, MatriksProvider)

    def test_official_provider_endpoint_override_selected(self):
        from bist_bot.config.settings import settings
        from bist_bot.dependencies import _build_data_provider

        with settings.override(
            DATA_PROVIDER="official",
            OFFICIAL_VENDOR="generic",
            OFFICIAL_API_BASE_URL="https://api.example.com",
            OFFICIAL_API_KEY="key",
            OFFICIAL_USERNAME="user",
            OFFICIAL_PASSWORD="pass",
            OFFICIAL_QUOTE_ENDPOINT="/vendor/quote",
        ):
            provider = _build_data_provider()
        assert isinstance(provider, OfficialProvider)
        assert provider.endpoints.quote == "/vendor/quote"

    def test_official_stub_selected(self):
        from bist_bot.config.settings import settings
        from bist_bot.dependencies import _build_data_provider

        with settings.override(DATA_PROVIDER="official_stub"):
            provider = _build_data_provider()
        assert isinstance(provider, OfficialProviderStub)

    def test_yfinance_selected_by_default(self):
        from bist_bot.config.settings import settings
        from bist_bot.dependencies import _build_data_provider

        with settings.override(DATA_PROVIDER="yfinance"):
            provider = _build_data_provider()
        from bist_bot.data.providers import YFinanceProvider

        assert isinstance(provider, YFinanceProvider)


class TestSettingsValidation:
    def test_validate_data_provider_official_missing_fields(self):
        from bist_bot.config.settings import settings

        with settings.override(
            DATA_PROVIDER="official",
            OFFICIAL_API_BASE_URL="",
            OFFICIAL_API_KEY="",
            OFFICIAL_USERNAME="",
            OFFICIAL_PASSWORD="",
        ):
            with pytest.raises(RuntimeError, match="Missing required settings"):
                settings.validate_data_provider_config()

    def test_validate_data_provider_official_all_fields(self):
        from bist_bot.config.settings import settings

        with settings.override(
            DATA_PROVIDER="official",
            OFFICIAL_API_BASE_URL="https://api.example.com",
            OFFICIAL_API_KEY="key",
            OFFICIAL_USERNAME="user",
            OFFICIAL_PASSWORD="pass",
        ):
            settings.validate_data_provider_config()

    def test_validate_data_provider_yfinance_passes(self):
        from bist_bot.config.settings import settings

        with settings.override(DATA_PROVIDER="yfinance"):
            settings.validate_data_provider_config()
