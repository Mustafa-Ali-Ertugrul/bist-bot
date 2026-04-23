from __future__ import annotations

from datetime import datetime

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


class DummySettings:
    MARKET_OPEN_HOUR = 9
    MARKET_CLOSE_HOUR = 18
    MARKET_WARMUP_MINUTES = 15
    MARKET_HALF_DAY_HOUR = 13
    SCAN_INTERVAL_MINUTES = 15


def test_scheduler_uses_tr_timezone(monkeypatch) -> None:
    scheduler = MarketScheduler(
        DummyScanner(), DummyNotifier(), settings=DummySettings()
    )
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
