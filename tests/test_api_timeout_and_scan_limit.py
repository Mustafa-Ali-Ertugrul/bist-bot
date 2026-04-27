"""Tests for API client timeout configuration and scan limit support."""

from __future__ import annotations

import os
import sys
import time
from typing import Any, cast
from unittest.mock import patch

import pandas as pd
from flask_jwt_extended import create_access_token

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dashboard import create_dashboard_app  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


class SlowFetcherSpy:
    def __init__(self, hang_duration: float = 30.0):
        self.hang_duration = hang_duration
        self.clear_calls: list[tuple[str, str | None]] = []

    def clear_cache(
        self,
        scope: str = "all",
        ticker: str | None = None,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        self.clear_calls.append((scope, ticker))

    def fetch_multi_timeframe_all(
        self,
        trend_period: str = "6mo",
        trend_interval: str = "1d",
        trigger_period: str = "1mo",
        trigger_interval: str = "15m",
        force_refresh: bool = False,
        limit: int | None = None,
    ):
        _ = limit
        import time
        time.sleep(self.hang_duration)
        return {"THYAO.IS": {"trend": object(), "trigger": object()}}

    def fetch_single(self, ticker, period="6mo", interval="1d", force=False):
        return pd.DataFrame(
            {
                "open": [float(i) for i in range(1, 81)],
                "high": [float(i) + 1 for i in range(1, 81)],
                "low": [float(i) - 0.5 for i in range(1, 81)],
                "close": [float(i) + 0.2 for i in range(1, 81)],
                "volume": [100 + i for i in range(80)],
            },
            index=pd.date_range("2025-01-01", periods=80),
        )

    def get_cached_analysis(self, cache_key: str, force: bool = False):
        return None

    def store_analysis(self, cache_key: str, value: Any) -> None:
        pass


class EngineSpy:
    def __init__(self, scan_signals=None):
        self.scan_signals = scan_signals or []

    def scan_all(self, data):
        return list(self.scan_signals)

    def get_actionable_signals(self, signals):
        return signals


class LimitedFetcherSpy:
    def __init__(self):
        self.fetch_calls: list[dict[str, Any]] = []

    def clear_cache(
        self,
        scope: str = "all",
        ticker: str | None = None,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        pass

    def fetch_multi_timeframe_all(
        self,
        trend_period: str = "6mo",
        trend_interval: str = "1d",
        trigger_period: str = "1mo",
        trigger_interval: str = "15m",
        force_refresh: bool = False,
        limit: int | None = None,
    ):
        self.fetch_calls.append({"limit": limit, "force_refresh": force_refresh})
        tickers = ["THYAO.IS", "ASELS.IS", "BIMAS.IS", "GARAN.IS", "AKBNK.IS"]
        if limit is not None and limit > 0:
            tickers = tickers[:limit]
        return {t: {"trend": object(), "trigger": object()} for t in tickers}

    def fetch_single(self, ticker, period="6mo", interval="1d", force=False):
        return pd.DataFrame(
            {
                "open": [float(i) for i in range(1, 81)],
                "high": [float(i) + 1 for i in range(1, 81)],
                "low": [float(i) - 0.5 for i in range(1, 81)],
                "close": [float(i) + 0.2 for i in range(1, 81)],
                "volume": [100 + i for i in range(80)],
            },
            index=pd.date_range("2025-01-01", periods=80),
        )

    def get_cached_analysis(self, cache_key: str, force: bool = False):
        return None

    def store_analysis(self, cache_key: str, value: Any) -> None:
        pass


def _build_client(tmp_path, fetcher, engine, **overrides):
    with settings.override(
        DB_PATH=str(tmp_path / "test.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
        **overrides,
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "test.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, fetcher), cast(Any, engine), db, broker=None)
        app.config["TESTING"] = True
        with app.app_context():
            token = create_access_token(identity="admin@bistbot.local")
        client = app.test_client()
    return client, fetcher, token


def test_scan_endpoint_returns_504_on_timeout(tmp_path):
    fetcher = SlowFetcherSpy(hang_duration=30.0)
    engine = EngineSpy()
    client, _fetcher, token = _build_client(
        tmp_path, fetcher, engine, SCAN_TIMEOUT_SECONDS=2
    )

    with settings.override(SCAN_TIMEOUT_SECONDS=2):
        start = time.time()
        response = client.post(
            '/api/scan',
            headers={'Authorization': f'Bearer {token}'},
        )
        elapsed = time.time() - start

    assert response.status_code == 504
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "error"
    assert "timed out" in payload["message"].lower()
    assert elapsed < 10, "Response should not wait for the full hang duration"


def test_scan_endpoint_succeeds_when_scan_completes_in_time(tmp_path):
    """Verify normal scan returns 200 when scan completes within timeout."""
    fetcher = LimitedFetcherSpy()
    engine = EngineSpy(
        [Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=5.2)]
    )
    client, _fetcher, token = _build_client(
        tmp_path, fetcher, engine, SCAN_TIMEOUT_SECONDS=30
    )

    response = client.post(
        "/api/scan",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert "signals" in payload


def test_scan_endpoint_respects_limit_query_param(tmp_path):
    """Verify that /api/scan?limit=N only scans N tickers."""
    fetcher = LimitedFetcherSpy()
    engine = EngineSpy()
    client, _fetcher, token = _build_client(
        tmp_path, fetcher, engine, SCAN_TIMEOUT_SECONDS=30
    )

    response = client.post(
        "/api/scan?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert len(fetcher.fetch_calls) == 1
    assert fetcher.fetch_calls[0]["limit"] == 2


def test_scan_endpoint_respects_limit_in_json_body(tmp_path):
    """Verify that /api/scan with limit in JSON body only scans N tickers."""
    fetcher = LimitedFetcherSpy()
    engine = EngineSpy()
    client, _fetcher, token = _build_client(
        tmp_path, fetcher, engine, SCAN_TIMEOUT_SECONDS=30
    )

    response = client.post(
        "/api/scan",
        json={"limit": 3},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert len(fetcher.fetch_calls) == 1
    assert fetcher.fetch_calls[0]["limit"] == 3


def test_scan_endpoint_no_limit_scans_all(tmp_path):
    """Verify that /api/scan without limit scans all tickers."""
    fetcher = LimitedFetcherSpy()
    engine = EngineSpy()
    client, _fetcher, token = _build_client(
        tmp_path, fetcher, engine, SCAN_TIMEOUT_SECONDS=30
    )

    response = client.post(
        "/api/scan",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert len(fetcher.fetch_calls) == 1
    assert fetcher.fetch_calls[0]["limit"] is None


def test_scan_limit_query_param_takes_precedence_over_body(tmp_path):
    """Verify that ?limit= takes precedence over JSON body limit."""
    fetcher = LimitedFetcherSpy()
    engine = EngineSpy()
    client, _fetcher, token = _build_client(
        tmp_path, fetcher, engine, SCAN_TIMEOUT_SECONDS=30
    )

    response = client.post(
        "/api/scan?limit=1",
        json={"limit": 5},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert len(fetcher.fetch_calls) == 1
    assert fetcher.fetch_calls[0]["limit"] == 1


def test_api_client_scan_timeout_setting():
    """Verify SCAN_API_TIMEOUT_SECONDS setting exists and defaults to 60."""
    assert hasattr(settings, "SCAN_API_TIMEOUT_SECONDS")
    assert settings.SCAN_API_TIMEOUT_SECONDS == 60


def test_api_client_uses_longer_timeout_for_scan():
    """Verify api_request uses SCAN_API_TIMEOUT_SECONDS for /api/scan paths."""
    from bist_bot.ui.runtime import api_request

    with settings.override(SCAN_API_TIMEOUT_SECONDS=45):
        with patch("bist_bot.ui.runtime.requests.request") as mock_req:
            mock_req.return_value = type("Response", (), {"ok": True})()
            api_request("POST", "/api/scan", json={})
            mock_req.assert_called_once()
            kwargs = mock_req.call_args[1]
            assert kwargs["timeout"] == 45


def test_api_client_uses_short_timeout_for_other_paths():
    """Verify api_request uses 10s timeout for non-scan paths."""
    from bist_bot.ui.runtime import api_request

    with patch("bist_bot.ui.runtime.requests.request") as mock_req:
        mock_req.return_value = type("Response", (), {"ok": True})()
        api_request("GET", "/api/signals/history")
        mock_req.assert_called_once()
        kwargs = mock_req.call_args[1]
        assert kwargs["timeout"] == 10


def test_api_client_explicit_timeout_overrides_default():
    """Verify explicit timeout kwarg overrides the default."""
    from bist_bot.ui.runtime import api_request

    with patch("bist_bot.ui.runtime.requests.request") as mock_req:
        mock_req.return_value = type("Response", (), {"ok": True})()
        api_request("POST", "/api/scan", json={}, timeout=120)
        kwargs = mock_req.call_args[1]
        assert kwargs["timeout"] == 120
