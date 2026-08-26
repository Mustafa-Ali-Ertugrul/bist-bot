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
    scheduler, scanner, _day = _eod_scheduler(monkeypatch, hour=18, minute=15)

    assert scheduler._pending_eod_close(scheduler._now()) is True
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_calls == 1

    # Same day: date-keyed guard blocks a second run.
    assert scheduler._pending_eod_close(scheduler._now()) is False
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_calls == 1


def test_eod_pass_no_double_run_next_morning(monkeypatch) -> None:
    scheduler, scanner, _day = _eod_scheduler(monkeypatch, hour=18, minute=15)
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_calls == 1

    # Next morning 10:00: trigger (18:12) not reached yet -> no run.
    morning, _, _ = _eod_scheduler(monkeypatch, hour=10, minute=0, day_offset=1)
    morning._eod_close_done_date = scheduler._eod_close_done_date
    assert morning._pending_eod_close(morning._now()) is False

    # Next day after close: fires again (new date key).
    evening, scanner2, _ = _eod_scheduler(monkeypatch, hour=18, minute=15, day_offset=1)
    evening._eod_close_done_date = scheduler._eod_close_done_date
    assert evening._pending_eod_close(evening._now()) is True
    evening._run_eod_close(evening._now())
    assert scanner2.eod_calls == 1


def test_eod_pass_skips_weekend_and_before_trigger(monkeypatch) -> None:
    # Saturday (2026-08-22): holiday -> never pending.
    sat, _, _ = _eod_scheduler(monkeypatch, hour=18, minute=30, day_offset=2)
    assert sat._pending_eod_close(sat._now()) is False

    # Thursday 18:05: continuous trading closed (18:00) but the closing
    # session (18:00-18:10) is still running -> EOD pass must wait (B1).
    early, _, _ = _eod_scheduler(monkeypatch, hour=18, minute=5)
    assert early._pending_eod_close(early._now()) is False

    # Thursday 17:45: continuous session still open -> not yet.
    mid, _, _ = _eod_scheduler(monkeypatch, hour=17, minute=45)
    assert mid._pending_eod_close(mid._now()) is False


def test_run_loop_prefers_eod_pass_over_idle_sleep(monkeypatch) -> None:
    """At 18:15 the loop must run the EOD pass instead of sleeping to tomorrow."""
    scanner = EodSpyScanner()
    scheduler = MarketScheduler(scanner, DummyNotifier(), settings=DummySettings())

    def fake_sleep(seconds: float) -> None:
        scheduler.running = False

    class FakeDateTime(datetime):
        current_hour = {"h": 18}

    @classmethod
    def _now(cls, tz=None):
        h = FakeDateTime.current_hour["h"]
        return datetime(2026, 8, 20, h, 33, tzinfo=tz)

    FakeDateTime.now = _now

    def advancing_sleep(seconds: float) -> None:
        # First poll advances the clock past the trigger so the outer loop
        # re-evaluates and takes the EOD branch; second poll stops the loop.
        if FakeDateTime.current_hour["h"] == 18:
            FakeDateTime.current_hour["h"] = 19
        else:
            scheduler.running = False

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    monkeypatch.setattr("bist_bot.scheduler.is_bist_open", lambda _dt: False)
    monkeypatch.setattr("bist_bot.scheduler.sleep", advancing_sleep)

    scheduler.run_loop()

    assert scanner.eod_calls == 1
    assert scanner.scan_calls == 0


# ---------------------------------------------------------------------------
# B2 — EOD failure != done + bounded retry + escalation
# ---------------------------------------------------------------------------


class FlakyEodScanner(EodSpyScanner):
    """EOD pass fails N times, then succeeds."""

    def __init__(self, fail_times: int = 1) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.eod_attempts = 0

    def close_positions_at_eod(self):
        self.eod_attempts += 1
        if self.eod_attempts <= self.fail_times:
            raise RuntimeError("fetch failed at eod")
        super().close_positions_at_eod()


class RecordingNotifier(DummyNotifier):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def send_message(self, message):
        self.messages.append(message)
        return True


def test_eod_failure_does_not_mark_done_and_retries(monkeypatch) -> None:
    scanner = FlakyEodScanner(fail_times=1)
    notifier = RecordingNotifier()
    scheduler = MarketScheduler(scanner, notifier, settings=DummySettings())
    _, _, day = _eod_scheduler(monkeypatch, hour=18, minute=15)
    assert day is not None

    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_attempts == 1
    # HATA ≠ DONE: pending kalir (retry penceresi dolana kadar beklemede).
    assert scheduler._eod_close_done_date is None
    assert scheduler._eod_next_retry_at is not None
    assert scheduler._pending_eod_close(scheduler._now()) is False  # retry oncesi bekle

    # Retry penceresi sonrasi: tekrar dener, basarir → DONE.
    class LaterDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 20, 18, 30, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", LaterDateTime)
    assert scheduler._pending_eod_close(scheduler._now()) is True
    scheduler._run_eod_close(scheduler._now())
    assert scanner.eod_attempts == 2
    assert scheduler._eod_close_done_date == datetime(2026, 8, 20).date()
    # Ilk hatada uyar, basarida ekstra mesaj yok (recovery log only).
    assert len([m for m in notifier.messages if "EOD" in m]) == 1


def test_eod_final_failure_escalates_and_never_marks_done(monkeypatch) -> None:
    scanner = FlakyEodScanner(fail_times=99)
    notifier = RecordingNotifier()
    scheduler = MarketScheduler(scanner, notifier, settings=DummySettings())
    _eod_scheduler(monkeypatch, hour=18, minute=15)

    scheduler._run_eod_close(scheduler._now())
    assert scheduler._eod_next_retry_at is not None  # ilk deneme → retry planla

    class LaterDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 20, 18, 40, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", LaterDateTime)
    scheduler._run_eod_close(scheduler._now())
    # DENEME BİTTİ: FAILED_FINAL → gün done DEĞIL, tekrar denenmez.
    assert scheduler._eod_close_done_date is None
    assert scheduler._eod_final_failed is True
    assert scheduler._pending_eod_close(scheduler._now()) is False
    escalations = [m for m in notifier.messages if "🚨" in m]
    assert len(escalations) == 1
    assert "EOD" in escalations[0]


# ---------------------------------------------------------------------------
# C3/C4 — watchdog + retry exhaustion escalation
# ---------------------------------------------------------------------------


def test_watchdog_alerts_on_stale_scans_with_cooldown(monkeypatch) -> None:
    notifier = RecordingNotifier()
    scheduler = MarketScheduler(DummyScanner(), notifier, settings=DummySettings())

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 20, 14, 0, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    from bist_bot.notifier import TR as _TR

    # Son basarili tarama 45 dk once → uyari.
    scheduler._last_scan_success_at = datetime(2026, 8, 20, 13, 15, tzinfo=_TR)
    scheduler._check_watchdog(scheduler._now())
    assert len(notifier.messages) == 1
    assert "Watchdog" in notifier.messages[0]

    # 10 dk sonra tekrar → cooldown icinde, yeni mesaj yok.
    class TenLater(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 20, 14, 10, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", TenLater)
    scheduler._check_watchdog(scheduler._now())
    assert len(notifier.messages) == 1


def test_watchdog_recovery_message_on_scan_success(monkeypatch) -> None:
    notifier = RecordingNotifier()
    scheduler = MarketScheduler(DummyScanner(), notifier, settings=DummySettings())

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 20, 14, 0, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    scheduler._watchdog_alerted_at = scheduler._now()
    scheduler._mark_scan_success(scheduler._now())
    assert scheduler._watchdog_alerted_at is None
    assert any("geri geldi" in m for m in notifier.messages)


def test_scan_retry_exhaustion_sends_escalation(monkeypatch) -> None:
    """Uc deneme de basarisiz → Telegram escalation + streak flag."""
    notifier = RecordingNotifier()
    scheduler = MarketScheduler(DummyScanner(), notifier, settings=DummySettings())
    scheduler.running = True

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 20, 11, 0, tzinfo=tz)

    monkeypatch.setattr("bist_bot.scheduler.datetime", FakeDateTime)
    monkeypatch.setattr("bist_bot.scheduler.is_bist_open", lambda _dt: True)

    sleep_calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        # 3 retry backoff'u (30/60/90) sonrasi grid-beklemesine gecilir;
        # donmus saatte kilitlenmemek icin 4. uykuda donguyu durdur.
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 4:
            scheduler.running = False

    monkeypatch.setattr("bist_bot.scheduler.sleep", fake_sleep)

    calls = {"n": 0}

    def always_dead_scan():
        calls["n"] += 1
        raise RuntimeError("down")

    scheduler.scanner = type("S", (), {"scan_once": staticmethod(always_dead_scan)})()
    scheduler.run_loop()
    escalations = [m for m in notifier.messages if "3 denemede" in m]
    assert len(escalations) == 1
    assert scheduler._scan_fail_streak is True
