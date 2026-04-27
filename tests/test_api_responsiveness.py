from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import time
from typing import Any, cast

import pandas as pd
from flask_jwt_extended import create_access_token

from dashboard import create_dashboard_app  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


class SlowFetcherSpy:
    def __init__(self, hang_duration: float = 30.0):
        self.hang_duration = hang_duration

    def clear_cache(self, scope: str = 'all', ticker=None, period=None, interval=None):
        pass

    def fetch_multi_timeframe_all(self, **kwargs):
        time.sleep(self.hang_duration)
        return {}

    def fetch_single(self, ticker, period='6mo', interval='1d', force=False, limit=None):
        return pd.DataFrame(
            {'open': [float(i) for i in range(1, 81)],
             'high': [float(i) + 1 for i in range(1, 81)],
             'low': [float(i) - 0.5 for i in range(1, 81)],
             'close': [float(i) + 0.2 for i in range(1, 81)],
             'volume': [100 + i for i in range(80)]},
            index=pd.date_range('2025-01-01', periods=80),
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


def test_scan_endpoint_returns_504_on_timeout(tmp_path):
    fetcher = SlowFetcherSpy(hang_duration=30.0)
    engine = EngineSpy()
    with settings.override(
        DB_PATH=str(tmp_path / 'timeout_test.db'),
        JWT_SECRET_KEY='test_secret_key_12345678901234567890',
        ADMIN_BOOTSTRAP_EMAIL='',
        ADMIN_BOOTSTRAP_PASSWORD_HASH='',
        CORS_ORIGINS=('http://localhost:8501',),
        SCAN_TIMEOUT_SECONDS=2,
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / 'timeout_test.db'))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, fetcher), cast(Any, engine), db, broker=None)
        app.config['TESTING'] = True
        with app.app_context():
            token = create_access_token(identity='admin@bistbot.local')
        client = app.test_client()

        start = time.time()
        response = client.post(
            '/api/scan',
            json={'force_refresh': True},
            headers={'Authorization': f'Bearer {token}'},
        )
        elapsed = time.time() - start

    assert response.status_code == 504
    payload = response.get_json()
    assert payload is not None
    assert payload['status'] == 'error'
    assert 'timed out' in payload['message'].lower()
    assert elapsed < 10, f'Response should not wait for the full hang duration ({elapsed:.1f}s)'


def test_scan_timeout_returns_quickly_without_waiting_on_context_manager(tmp_path):
    fetcher = SlowFetcherSpy(hang_duration=30.0)
    engine = EngineSpy()
    with settings.override(
        DB_PATH=str(tmp_path / 'timeout_test2.db'),
        JWT_SECRET_KEY='test_secret_key_12345678901234567890',
        ADMIN_BOOTSTRAP_EMAIL='',
        ADMIN_BOOTSTRAP_PASSWORD_HASH='',
        CORS_ORIGINS=('http://localhost:8501',),
        SCAN_TIMEOUT_SECONDS=1,
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / 'timeout_test2.db'))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, fetcher), cast(Any, engine), db, broker=None)
        app.config['TESTING'] = True
        with app.app_context():
            token = create_access_token(identity='admin@bistbot.local')
        client = app.test_client()

        start = time.time()
        response = client.post(
            '/api/scan',
            headers={'Authorization': f'Bearer {token}'},
        )
        elapsed = time.time() - start

    assert response.status_code == 504
    assert elapsed < 5, f'Should return quickly without waiting for the hung thread ({elapsed:.1f}s)'


class FastFetcherSpy:
    def clear_cache(self, scope='all', ticker=None, period=None, interval=None):
        pass

    def fetch_multi_timeframe_all(self, **kwargs):
        return {'THYAO.IS': {'trend': object(), 'trigger': object()}}

    def fetch_single(self, ticker, period='6mo', interval='1d', force=False, limit=None):
        return pd.DataFrame({'close': [1.0, 2.0]})

    def get_cached_analysis(self, cache_key, force=False):
        return None

    def store_analysis(self, cache_key, value):
        pass


def test_scan_endpoint_succeeds_when_scan_completes_in_time(tmp_path):
    engine = EngineSpy(
        [Signal(ticker='THYAO.IS', signal_type=SignalType.BUY, score=25, price=5.2)]
    )
    with settings.override(
        DB_PATH=str(tmp_path / 'fast_test.db'),
        JWT_SECRET_KEY='test_secret_key_12345678901234567890',
        ADMIN_BOOTSTRAP_EMAIL='',
        ADMIN_BOOTSTRAP_PASSWORD_HASH='',
        CORS_ORIGINS=('http://localhost:8501',),
        SCAN_TIMEOUT_SECONDS=10,
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / 'fast_test.db'))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, FastFetcherSpy()), cast(Any, engine), db, broker=None)
        app.config['TESTING'] = True
        with app.app_context():
            token = create_access_token(identity='admin@bistbot.local')
        client = app.test_client()

        response = client.post(
            '/api/scan',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'ok'
    assert 'signals' in payload
