"""Tests for BIST market calendar: holidays, session detection, next session."""

from __future__ import annotations

from datetime import date, datetime

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
