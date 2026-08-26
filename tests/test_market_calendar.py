"""Tests for BIST market calendar: holidays, session detection, next session."""

from __future__ import annotations

from datetime import date, datetime, time

from bist_bot.market_calendar import (
    TR,
    is_bist_holiday,
    is_bist_open,
    next_bist_session,
)


class TestIsBistHoliday:
    def test_weekday_not_holiday(self):
        assert is_bist_holiday(date(2025, 1, 6)) is False

    def test_saturday_is_holiday(self):
        assert is_bist_holiday(date(2025, 1, 4)) is True

    def test_sunday_is_holiday(self):
        assert is_bist_holiday(date(2025, 1, 5)) is True

    def test_republic_day_holiday(self):
        assert is_bist_holiday(date(2025, 10, 29)) is True


class TestIsBistOpen:
    def test_during_market_hours(self):
        dt = datetime(2025, 1, 6, 11, 0, tzinfo=TR)
        assert is_bist_open(dt) is True

    def test_before_market(self):
        dt = datetime(2025, 1, 6, 9, 0, tzinfo=TR)
        assert is_bist_open(dt) is False

    def test_after_market(self):
        dt = datetime(2025, 1, 6, 18, 0, tzinfo=TR)
        assert is_bist_open(dt) is False

    def test_holiday_not_open(self):
        dt = datetime(2025, 10, 29, 11, 0, tzinfo=TR)
        assert is_bist_open(dt) is False

    def test_weekend_not_open(self):
        dt = datetime(2025, 1, 4, 11, 0, tzinfo=TR)
        assert is_bist_open(dt) is False


class TestNextBistSession:
    def test_weekday_morning_returns_same_day(self):
        dt = datetime(2025, 1, 6, 7, 0, tzinfo=TR)
        nxt = next_bist_session(dt)
        assert nxt.date() == date(2025, 1, 6)
        assert nxt.hour == 10

    def test_after_close_returns_next_day(self):
        dt = datetime(2025, 1, 6, 18, 0, tzinfo=TR)
        nxt = next_bist_session(dt)
        assert nxt.date() == date(2025, 1, 7)

    def test_friday_evening_skips_to_monday(self):
        dt = datetime(2025, 1, 3, 18, 0, tzinfo=TR)
        nxt = next_bist_session(dt)
        assert nxt.weekday() == 0


# ---------------------------------------------------------------------------
# B1 — continuous close 18:00 vs session close 18:10 (kapanis seansi)
# ---------------------------------------------------------------------------


class TestSessionModel:
    def test_1745_continuous_session_open(self):
        assert is_bist_open(datetime(2025, 1, 6, 17, 45, tzinfo=TR)) is True

    def test_1800_continuous_closed(self):
        # Surekli islem 18:00'de biter (eski kod 17:30'da bitiriyordu — bug).
        assert is_bist_open(datetime(2025, 1, 6, 18, 0, tzinfo=TR)) is False

    def test_close_time_from_settings(self):
        from bist_bot.market_calendar import bist_close_time

        assert bist_close_time(date(2025, 1, 6)) == time(18, 0)

    def test_session_close_includes_closing_auction(self):
        from bist_bot.market_calendar import bist_session_close_time

        assert bist_session_close_time(date(2025, 1, 6)) == time(18, 10)

    def test_eod_time_after_session_close(self):
        from bist_bot.market_calendar import bist_eod_time

        # EOD muhasebesi kapanis seansi BITTIKTEN sonra (18:10 + 2dk = 18:12).
        assert bist_eod_time(date(2025, 1, 6)) == time(18, 12)

    def test_1805_is_not_eod_time_yet(self):
        # 18:05 kapanis seansi icinde → EOD tetiklenmemeli (scheduler testiyle
        # birlikte bu, eski 17:32 erken-kapanis davranisindan ayirir).
        from bist_bot.market_calendar import bist_eod_time

        assert time(18, 5) < bist_eod_time(date(2025, 1, 6))

    def test_next_session_after_1800_not_before(self):
        # 18:00 sonrasi ayni gun seans yok → ertesi gun.
        nxt = next_bist_session(datetime(2025, 1, 6, 18, 5, tzinfo=TR))
        assert nxt.date() == date(2025, 1, 7)


class TestCalendarExpiry:
    def test_valid_until_2030(self):
        from bist_bot.market_calendar import holiday_calendar_valid_until

        assert holiday_calendar_valid_until() == date(2030, 12, 31)

    def test_warn_only_when_expiring(self):
        from bist_bot.market_calendar import warn_if_calendar_expiring

        # Bugun icin asla uyarmamali (2030'a cok var).
        assert warn_if_calendar_expiring(days_ahead=60) is False
        # Sinir: gunler ilerledikce sadece valid_until yakinsa True.
        assert warn_if_calendar_expiring(days_ahead=(2030 - 2026) * 366) is False
