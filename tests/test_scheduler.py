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


# ---------------------------------------------------------------------------
# Faz 3 P1.1 — post-close EOD pass (once per day, no morning double-run)
# ---------------------------------------------------------------------------


class EodSpyScanner:
    def __init__(self) -> None:
        self.scan_calls = 0
        self.eod_calls = 0

    def scan_once(self):
        self.scan_calls += 1
        return []

    def close_positions_at_eod(self):
        self.eod_calls += 1


def _eod_scheduler(monkeypatch, *, hour: int, minute: int, day_offset: int = 0):
    """Build a scheduler whose clock is pinned to a TR weekday afternoon."""
    from datetime import date as _date
    from datetime import timedelta as _td

    scanner = EodSpyScanner()
    scheduler = MarketScheduler(scanner, DummyNotifier(), settings=DummySettings())
    base_day = _date(2026, 8, 20) + _td(days=day_offset)  # 2026-08-20 = Thursday

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(base_day, datetime.min.time(), tzinfo=tz).replace(
                hour=hour, minute=minute
            )

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    return scheduler, scanner, base_day


def test_eod_pass_fires_once_after_close_and_not_again_same_day(monkeypatch) -> None:
    scheduler, scanner, _day = _eod_scheduler(monkeypatch, hour=17, minute=33)

    assert scheduler._pending_eod_close(scheduler._now()) is True
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_calls == 1

    # Same day: date-keyed guard blocks a second run.
    assert scheduler._pending_eod_close(scheduler._now()) is False
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_calls == 1


def test_eod_pass_no_double_run_next_morning(monkeypatch) -> None:
    scheduler, scanner, _day = _eod_scheduler(monkeypatch, hour=17, minute=33)
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_calls == 1

    # Next morning 10:00: trigger (17:32) not reached yet -> no run.
    morning, _, _ = _eod_scheduler(monkeypatch, hour=10, minute=0, day_offset=1)
    morning._eod_close_done_date = scheduler._eod_close_done_date
    assert morning._pending_eod_close(morning._now()) is False

    # Next day after close: fires again (new date key).
    evening, scanner2, _ = _eod_scheduler(monkeypatch, hour=17, minute=33, day_offset=1)
    evening._eod_close_done_date = scheduler._eod_close_done_date
    assert evening._pending_eod_close(evening._now()) is True
    evening._run_eod_close(evening._now())
    assert scanner2.eod_calls == 1


def test_eod_pass_skips_weekend_and_before_trigger(monkeypatch) -> None:
    # Saturday (2026-08-22): holiday -> never pending.
    sat, _, _ = _eod_scheduler(monkeypatch, hour=18, minute=0, day_offset=2)
    assert sat._pending_eod_close(sat._now()) is False

    # Thursday 17:15: before trigger (17:32) -> not yet.
    early, _, _ = _eod_scheduler(monkeypatch, hour=17, minute=15)
    assert early._pending_eod_close(early._now()) is False


def test_run_loop_prefers_eod_pass_over_idle_sleep(monkeypatch) -> None:
    """At 17:33 the loop must run the EOD pass instead of sleeping to tomorrow."""
    scanner = EodSpyScanner()
    scheduler = MarketScheduler(scanner, DummyNotifier(), settings=DummySettings())

    def fake_sleep(seconds: float) -> None:
        scheduler.running = False

    class FakeDateTime(datetime):
        current_hour = {"h": 17}

        @classmethod
        def now(cls, tz=None):
            h = FakeDateTime.current_hour["h"]
            return datetime(2026, 8, 20, h, 33, tzinfo=tz)

    def advancing_sleep(seconds: float) -> None:
        # First poll advances the clock past the trigger so the outer loop
        # re-evaluates and takes the EOD branch; second poll stops the loop.
        if FakeDateTime.current_hour["h"] == 17:
            FakeDateTime.current_hour["h"] = 18
        else:
            scheduler.running = False

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    monkeypatch.setattr("bist_bot.scheduler.is_bist_open", lambda _dt: False)
    monkeypatch.setattr("bist_bot.scheduler.sleep", advancing_sleep)

    scheduler.run_loop()

    assert scanner.eod_calls == 1
    assert scanner.scan_calls == 0
