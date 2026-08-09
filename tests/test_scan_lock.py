"""Single-writer scan lock tests: unit + ScanService/runtime integration."""

from __future__ import annotations

import os
import sys
import threading
from unittest.mock import MagicMock

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.scanner import ScanService  # noqa: E402
from bist_bot.ui import runtime_scan  # noqa: E402
from bist_bot.utils.scan_lock import ScanLock  # noqa: E402


def test_lock_excludes_second_acquirer(tmp_path):
    lock_path = str(tmp_path / "scan.lock")
    lock1 = ScanLock(lock_path)
    lock2 = ScanLock(lock_path)

    assert lock1.acquire() is True
    assert lock2.acquire() is False
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()


def test_lock_release_is_idempotent(tmp_path):
    lock = ScanLock(str(tmp_path / "scan.lock"))
    assert lock.acquire() is True
    lock.release()
    lock.release()


def test_lock_context_manager_raises_when_busy(tmp_path):
    lock_path = str(tmp_path / "scan.lock")
    lock1 = ScanLock(lock_path)
    lock2 = ScanLock(lock_path)

    with lock1:
        with pytest.raises(RuntimeError, match="already running"):
            with lock2:
                pass


def test_lock_acquire_timeout_when_held(tmp_path):
    lock_path = str(tmp_path / "scan.lock")
    lock1 = ScanLock(lock_path)
    lock2 = ScanLock(lock_path)

    assert lock1.acquire() is True
    assert lock2.acquire(timeout=0.2) is False
    lock1.release()
    assert lock2.acquire(timeout=0.2) is True
    lock2.release()


def test_lock_serializes_threads(tmp_path):
    lock_path = str(tmp_path / "scan.lock")
    lock = ScanLock(lock_path)
    state = {"active": 0, "max_active": 0}
    gate = threading.Barrier(6)

    def worker(worker_id: int) -> None:
        gate.wait()
        if not lock.acquire(timeout=5.0):
            return
        try:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            threading.Event().wait(0.05)
            state["active"] -= 1
        finally:
            lock.release()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert state["max_active"] <= 1


def _build_service(tmp_path, *, scan_lock: ScanLock | None = None) -> ScanService:
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    engine.scan_all.return_value = []
    engine.get_actionable_signals.return_value = []
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "",
    }
    notifier = MagicMock()
    db = MagicMock()
    return ScanService(
        fetcher,
        engine,
        notifier,
        db,
        scan_lock=scan_lock or ScanLock(str(tmp_path / "service.lock")),
        scan_lock_timeout=0.0,
    )


def test_scan_once_skips_when_lock_held(tmp_path):
    service = _build_service(tmp_path)
    assert service.scan_lock.acquire() is True

    result = service.scan_once()

    assert result == []
    service.fetcher.fetch_multi_timeframe_all.assert_not_called()
    service.scan_lock.release()


def test_scan_once_runs_after_lock_released(tmp_path):
    service = _build_service(tmp_path)
    assert service.scan_lock.acquire() is True
    service.scan_lock.release()

    result = service.scan_once()

    assert result == []
    service.fetcher.fetch_multi_timeframe_all.assert_called_once()


def test_scan_once_releases_lock_even_on_exception(tmp_path):
    service = _build_service(tmp_path)
    service.fetcher.fetch_multi_timeframe_all.side_effect = RuntimeError("fetch boom")

    with pytest.raises(RuntimeError, match="fetch boom"):
        service.scan_once()

    assert service.scan_lock.acquire() is True
    service.scan_lock.release()


def test_collect_scan_result_skips_when_lock_held(tmp_path):
    holder = ScanLock(str(tmp_path / "ui.lock"))
    assert holder.acquire() is True

    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    original_impl = runtime_scan._collect_scan_result_impl
    original_lock = runtime_scan.UI_SCAN_LOCK
    impl_mock = MagicMock(return_value={"signals": []})
    runtime_scan._collect_scan_result_impl = impl_mock
    runtime_scan.UI_SCAN_LOCK = ScanLock(str(tmp_path / "ui.lock"))
    try:
        result = runtime_scan.collect_scan_result(fetcher, engine, notifier, db)
    finally:
        holder.release()
        runtime_scan._collect_scan_result_impl = original_impl
        runtime_scan.UI_SCAN_LOCK = original_lock

    assert result is not None
    assert result.get("error") is not None
    impl_mock.assert_not_called()


def test_collect_scan_result_runs_when_lock_free(tmp_path):
    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    original_impl = runtime_scan._collect_scan_result_impl
    original_lock = runtime_scan.UI_SCAN_LOCK
    mock_result = {"signals": [], "scan_stats": {"generated": 0, "actionable": 0, "hold": 0}}
    impl_mock = MagicMock(return_value=mock_result)
    runtime_scan._collect_scan_result_impl = impl_mock
    runtime_scan.UI_SCAN_LOCK = ScanLock(str(tmp_path / "ui_free.lock"))
    try:
        result = runtime_scan.collect_scan_result(fetcher, engine, notifier, db)
    finally:
        runtime_scan._collect_scan_result_impl = original_impl
        runtime_scan.UI_SCAN_LOCK = original_lock

    assert result == mock_result
    impl_mock.assert_called_once()