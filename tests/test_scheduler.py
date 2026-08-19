from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from bist_bot.scheduler import MarketScheduler


class DummyScanner:
    def __init__(self) -> None:
        self.calls = 0
        self.scheduler: MarketScheduler | None = None

    def scan_once(self):
        self.calls += 1
        if self.scheduler is not None:
            self.scheduler.running = False


class DummyNotifier:
    def __init__(self) -> None:
        self.calls = 0

    def send_startup_message(self):
        self.calls += 1
        return True

    def send_message(self, message):
        pass


class DummySettings:
    MARKET_OPEN_HOUR = 9
    MARKET_CLOSE_HOUR = 18
    MARKET_WARMUP_MINUTES = 15
    MARKET_HALF_DAY_HOUR = 13
    SCAN_INTERVAL_MINUTES = 15

    class agent:
        AGENT_ENABLED = True


def test_scheduler_uses_tr_timezone(monkeypatch) -> None:
    scheduler = MarketScheduler(DummyScanner(), DummyNotifier(), settings=DummySettings())
    seen = {"tz": None}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            seen["tz"] = tz
            return datetime(2025, 1, 2, 10, 0, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)

    now = scheduler._now()

    assert seen["tz"] is not None
    assert getattr(seen["tz"], "utcoffset", lambda _dt: None)(None) is not None
    assert now.tzinfo is seen["tz"]


def test_scheduler_closed_market_uses_idle_poll(monkeypatch) -> None:
    scheduler = MarketScheduler(DummyScanner(), DummyNotifier(), settings=DummySettings())
    slept = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        scheduler.running = False

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 3, 8, 30, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    monkeypatch.setattr("bist_bot.scheduler.is_bist_open", lambda _date: False)
    monkeypatch.setattr("bist_bot.scheduler.sleep", fake_sleep)

    scheduler.run_loop()

    # _sleep_until_next_session polls in 10s chunks (responsive shutdown),
    # not a single 60s sleep, and the first poll flips `running` to False.
    assert slept == [10]


def test_scheduler_keeps_normal_interval_after_13_on_full_day(monkeypatch) -> None:
    scanner = DummyScanner()
    scheduler = MarketScheduler(scanner, DummyNotifier(), settings=DummySettings())
    slept = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        scheduler.running = False

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 28, 13, 4, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    monkeypatch.setattr("bist_bot.scheduler.is_bist_open", lambda _date: True)
    monkeypatch.setattr("bist_bot.scheduler.sleep", fake_sleep)

    scheduler.run_loop()

    assert scanner.calls == 1
    assert slept == [10]


class RetryScanner:
    """Scanner that fails first time, succeeds on retry."""

    def __init__(self) -> None:
        self.calls = 0
        self.scheduler: MarketScheduler | None = None

    def scan_once(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        if self.scheduler is not None:
            self.scheduler.running = False
        return []


def test_scheduler_retry_calls_agent_callback(monkeypatch) -> None:
    """BUG-5: scheduler retry success must also call trading_agent.on_scan_completed."""
    scanner = RetryScanner()
    notifier = DummyNotifier()
    agent = MagicMock()
    scheduler = MarketScheduler(scanner, notifier, settings=DummySettings(), trading_agent=agent)
    scanner.scheduler = scheduler

    def fake_sleep(seconds: float) -> None:
        pass

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 6, 10, 0, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    monkeypatch.setattr("bist_bot.scheduler.is_bist_open", lambda _date: True)
    monkeypatch.setattr("bist_bot.scheduler.sleep", fake_sleep)

    with monkeypatch.context() as m:
        m.setattr(scheduler.settings, "agent", type("A", (), {"AGENT_ENABLED": True})())
        scheduler.run_loop()

    agent.on_scan_completed.assert_called()
