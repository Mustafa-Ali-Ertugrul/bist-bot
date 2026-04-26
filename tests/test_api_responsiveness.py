"""Tests for API startup responsiveness and Cloud Run readiness."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from bist_bot.config.settings import settings

# ── /ready endpoint tests ──────────────────────────────────────────────────


def test_ready_returns_200_without_db_ping():
    """The /ready endpoint must not call db.ping() or any external service."""
    from bist_bot.contracts import (
        DataFetcherProtocol,
        SignalRepositoryProtocol,
        StrategyEngineProtocol,
    )
    from bist_bot.dashboard import create_dashboard_app

    class FakeFetcher(DataFetcherProtocol):
        def fetch_all(self, *a, **kw):
            return {}

        def fetch_single(self, *a, **kw):
            return None

    class FakeEngine(StrategyEngineProtocol):
        def scan_all(self, *a, **kw):
            return []

    class FakeRepo(SignalRepositoryProtocol):
        def get_recent_signals(self, *a, **kw):
            return []

        def save_signal(self, *a, **kw):
            pass

        ping_called = False

        def ping(self):
            self.ping_called = True
            return True

    repo = FakeRepo()
    with settings.override(JWT_SECRET_KEY="test-secret-key-for-responsiveness-tests"):
        app = create_dashboard_app(
            fetcher=FakeFetcher(),
            engine=FakeEngine(),
            db=repo,
        )

    with app.test_client() as client:
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ready"
        assert not repo.ping_called, "/ready must not call db.ping()"


# ── /health endpoint tests ─────────────────────────────────────────────────


def test_health_returns_degraded_when_db_fails():
    """If db.ping() raises, /health returns 503 with degraded status."""
    from bist_bot.contracts import (
        DataFetcherProtocol,
        SignalRepositoryProtocol,
        StrategyEngineProtocol,
    )
    from bist_bot.dashboard import create_dashboard_app

    class FakeFetcher(DataFetcherProtocol):
        def fetch_all(self, *a, **kw):
            return {}

        def fetch_single(self, *a, **kw):
            return None

    class FakeEngine(StrategyEngineProtocol):
        def scan_all(self, *a, **kw):
            return []

    class FakeRepo(SignalRepositoryProtocol):
        def get_recent_signals(self, *a, **kw):
            return []

        def save_signal(self, *a, **kw):
            pass

        def ping(self):
            return False

    with settings.override(JWT_SECRET_KEY="test-secret-key-for-responsiveness-tests"):
        app = create_dashboard_app(
            fetcher=FakeFetcher(),
            engine=FakeEngine(),
            db=FakeRepo(),
        )

    with app.test_client() as client:
        response = client.get("/health")
        assert response.status_code == 503
        data = response.get_json()
        assert data["status"] == "degraded"
        assert data["database"] == "error"


def test_health_returns_healthy_when_db_ok():
    """If db.ping() succeeds, /health returns 200."""
    from bist_bot.contracts import (
        DataFetcherProtocol,
        SignalRepositoryProtocol,
        StrategyEngineProtocol,
    )
    from bist_bot.dashboard import create_dashboard_app

    class FakeFetcher(DataFetcherProtocol):
        def fetch_all(self, *a, **kw):
            return {}

        def fetch_single(self, *a, **kw):
            return None

    class FakeEngine(StrategyEngineProtocol):
        def scan_all(self, *a, **kw):
            return []

    class FakeRepo(SignalRepositoryProtocol):
        def get_recent_signals(self, *a, **kw):
            return []

        def save_signal(self, *a, **kw):
            pass

        def ping(self):
            return True

    with settings.override(JWT_SECRET_KEY="test-secret-key-for-responsiveness-tests"):
        app = create_dashboard_app(
            fetcher=FakeFetcher(),
            engine=FakeEngine(),
            db=FakeRepo(),
        )

    with app.test_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"


# ── Login responsiveness tests ─────────────────────────────────────────────


def test_login_bad_credentials_returns_401_quickly():
    """Invalid credentials must return 401 without delay."""
    from bist_bot.contracts import (
        DataFetcherProtocol,
        SignalRepositoryProtocol,
        StrategyEngineProtocol,
    )
    from bist_bot.dashboard import create_dashboard_app

    class FakeFetcher(DataFetcherProtocol):
        def fetch_all(self, *a, **kw):
            return {}

        def fetch_single(self, *a, **kw):
            return None

    class FakeEngine(StrategyEngineProtocol):
        def scan_all(self, *a, **kw):
            return []

    class FakeRepo(SignalRepositoryProtocol):
        def get_recent_signals(self, *a, **kw):
            return []

        def save_signal(self, *a, **kw):
            pass

        def ping(self):
            return True

        @property
        def manager(self):
            return None

    with settings.override(JWT_SECRET_KEY="test-secret-key-for-responsiveness-tests"):
        app = create_dashboard_app(
            fetcher=FakeFetcher(),
            engine=FakeEngine(),
            db=FakeRepo(),
        )

    with app.test_client() as client:
        start = time.monotonic()
        response = client.post(
            "/api/auth/login",
            json={"email": "fake@test.com", "password": "wrong"},
        )
        elapsed = time.monotonic() - start
        assert response.status_code == 401
        assert elapsed < 2.0, f"Login took {elapsed:.2f}s, should be < 2s"


# ── Lazy watchlist resolution tests ────────────────────────────────────────


def test_fetcher_init_without_watchlist_does_not_call_network():
    """BISTDataFetcher.__init__ with watchlist=None must not trigger fetch_universe."""
    with patch("bist_bot.data.fetcher.YFinanceProvider") as MockProvider:
        mock_provider = MagicMock()
        MockProvider.return_value = mock_provider

        from bist_bot.data.fetcher import BISTDataFetcher

        fetcher = BISTDataFetcher(watchlist=None, provider=mock_provider)

        mock_provider.fetch_universe.assert_not_called()

        # Accessing watchlist should trigger the fetch
        mock_provider.fetch_universe.return_value = ["THYAO.IS", "ASELS.IS"]
        _ = fetcher.watchlist
        mock_provider.fetch_universe.assert_called_once()


def test_fetcher_init_with_watchlist_does_not_call_network():
    """BISTDataFetcher.__init__ with explicit watchlist must not call network."""
    with patch("bist_bot.data.fetcher.YFinanceProvider") as MockProvider:
        mock_provider = MagicMock()
        MockProvider.return_value = mock_provider

        from bist_bot.data.fetcher import BISTDataFetcher

        fetcher = BISTDataFetcher(watchlist=["THYAO.IS"], provider=mock_provider)

        mock_provider.fetch_universe.assert_not_called()
        assert fetcher.watchlist == ["THYAO.IS"]
