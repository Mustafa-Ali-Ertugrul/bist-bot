import threading
import time
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from flask_jwt_extended import create_access_token

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.scanner import ScanAbortedError, ScanService
from bist_bot.strategy.signal_models import Signal, SignalType


class FakeFetcher:
    def __init__(self):
        self.watchlist = ["THYAO.IS"]

    def fetch_multi_timeframe_all(self, **kwargs):
        return {"THYAO.IS": {"trigger": MagicMock()}}

    def clear_cache(self, **kwargs):
        pass


class FakeEngine:
    def __init__(self, signals=None):
        self._signals = signals or [
            Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=30.0, price=300.0)
        ]

    def scan_all(self, data):
        return list(self._signals)

    def get_actionable_signals(self, signals):
        return [s for s in signals if s.score >= 25.0]

    def get_last_rejection_breakdown(self):
        return {}


def _build_client(tmp_path, scan_service_override=None, scan_signals=None):
    db_path = str(tmp_path / "test_lifecycle.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        db = DataAccess(manager)
        fetcher = FakeFetcher()
        engine = FakeEngine(signals=scan_signals)
        app = create_dashboard_app(cast(Any, fetcher), cast(Any, engine), db)
        app.config["TESTING"] = True

        if scan_service_override is not None:
            app.config["scan_service_factory"] = lambda: scan_service_override

        with app.app_context():
            token = create_access_token(identity="admin@bistbot.local")
        client = app.test_client()
    return client, token


def test_scan_completes_within_timeout_returns_200(tmp_path):
    client, token = _build_client(tmp_path)
    res = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert len(data["signals"]) == 1
    assert data["signals"][0]["ticker"] == "THYAO.IS"


def test_scan_times_out_and_aborts_cooperatively(tmp_path):
    mock_service = MagicMock()
    abort_seen = threading.Event()

    def slow_scan(force_refresh=False, abort_event=None):
        for _ in range(20):
            time.sleep(0.02)
            if abort_event and abort_event.is_set():
                abort_seen.set()
                raise ScanAbortedError("Aborted on timeout")
        return []

    mock_service.scan_once.side_effect = slow_scan
    client, token = _build_client(tmp_path, scan_service_override=mock_service)

    with settings.override(SCAN_TIMEOUT_SECONDS=1):
        # We simulate a 0.05s timeout via override
        pass

    with settings.override(SCAN_TIMEOUT_SECONDS=0.05):
        t0 = time.monotonic()
        res = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})
        t1 = time.monotonic()

    assert res.status_code == 504
    assert t1 - t0 < 0.25  # Bounded execution
    data = res.get_json()
    assert data["status"] == "error"
    assert "timed out" in data["message"].lower()
    # Ensure cooperative cancellation event fired
    assert abort_seen.wait(timeout=1.0)


def test_scan_in_flight_blocks_concurrent_runs_with_429(tmp_path):
    mock_service = MagicMock()
    started_event = threading.Event()
    continue_event = threading.Event()

    def blocking_scan(force_refresh=False, abort_event=None):
        started_event.set()
        continue_event.wait(timeout=2.0)
        return []

    mock_service.scan_once.side_effect = blocking_scan
    mock_service.last_scan_stats = {"scanned": 0, "signals": 0, "actionable": 0}
    mock_service.last_rejection_breakdown = {}

    client, token = _build_client(tmp_path, scan_service_override=mock_service)

    results = []

    def req1():
        results.append(client.post("/api/scan", headers={"Authorization": f"Bearer {token}"}))

    t = threading.Thread(target=req1)
    t.start()

    assert started_event.wait(timeout=1.0)

    # While req1 is active, req2 should immediately get 429
    res2 = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code == 429
    assert "already in progress" in res2.get_json()["message"].lower()

    continue_event.set()
    t.join(timeout=2.0)
    assert results[0].status_code == 200


def test_scan_service_strict_discard_on_abort():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {"THYAO.IS": {}}
    engine = MagicMock()
    engine.scan_all.return_value = [
        Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=30.0, price=300.0)
    ]
    notifier = MagicMock()
    db = MagicMock()

    service = ScanService(
        fetcher=fetcher,
        engine=engine,
        notifier=notifier,
        db=db,
        settings=settings.replace(WATCHLIST=["THYAO.IS"]),
    )

    abort = threading.Event()
    abort.set()  # Pre-abort before scan

    with pytest.raises(ScanAbortedError):
        service.scan_once(abort_event=abort)

    # Verify strict discard: neither signals nor scan logs were saved or notified
    db.save_signals.assert_not_called()
    db.save_scan_log.assert_not_called()
    notifier.send_signal.assert_not_called()
