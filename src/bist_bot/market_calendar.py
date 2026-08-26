"""BIST market calendar: holiday detection, session windows, and next-session calculator.

Turkey abolished DST in 2016, so TR = UTC+3 year-round.

Session model (BIST Pay Piyasası):
- Continuous trading window: MARKET_OPEN_HOUR..MARKET_CLOSE_HOUR (10:00-18:00).
- Closing/Single-Price session: continuous close + SESSION_CLOSE_BUFFER_MINUTES
  (18:00-18:10). Scanners stop at the continuous close; EOD reconciliation
  runs only after the full session close.

All times are single-sourced from settings (env-overridable); no hardcoded
session hours appear elsewhere. Holiday data covers 2020-2031 — extend
``_TR_HOLIDAYS`` before then; ``holiday_calendar_valid_until()`` supports
expiry warnings (fail-loud policy is applied by callers).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from bist_bot.app_logging import get_logger

try:
    import holidays as _holidays

    _HOLIDAY_YEARS = range(2020, 2031)
    _TR_HOLIDAYS: Any = _holidays.Turkey(years=_HOLIDAY_YEARS)
except (ImportError, AttributeError):
    _HOLIDAY_YEARS = range(2020, 2031)
    _TR_HOLIDAYS = {}

logger = get_logger(__name__, component="market_calendar")

TR = timezone(timedelta(hours=3))

_HOLIDAY_MAX_YEAR = 2030  # inclusive

_HALF_DAY_DATES: set[date] = set()


def _market_hours() -> tuple[int, int, int]:
    """(open_hour, continuous_close_hour, session_close_buffer_minutes) from settings."""
    from bist_bot.config.settings import settings

    return (
        int(getattr(settings, "MARKET_OPEN_HOUR", 10)),
        int(getattr(settings, "MARKET_CLOSE_HOUR", 18)),
        int(getattr(settings, "SESSION_CLOSE_BUFFER_MINUTES", 10)),
    )


def _half_day_hour() -> int:
    from bist_bot.config.settings import settings

    return int(getattr(settings, "MARKET_HALF_DAY_HOUR", 13))


def holiday_calendar_valid_until() -> date:
    """Last date the bundled holiday calendar is known to cover."""
    return date(_HOLIDAY_MAX_YEAR, 12, 31)


def warn_if_calendar_expiring(days_ahead: int = 60) -> bool:
    """Log a warning when the holiday calendar is close to expiry. True if expiring."""
    remaining = (holiday_calendar_valid_until() - datetime.now(TR).date()).days
    if remaining < days_ahead:
        logger.warning(
            "market_calendar_expiring",
            valid_until=str(holiday_calendar_valid_until()),
            remaining_days=remaining,
        )
        return True
    return False


def is_bist_holiday(d: date) -> bool:
    return d.weekday() >= 5 or d in _TR_HOLIDAYS


def is_bist_half_day(d: date) -> bool:
    return d in _HALF_DAY_DATES


def is_bist_open(dt: datetime | None = None) -> bool:
    """True inside the continuous trading window (scanner operates here)."""
    if dt is None:
        dt = datetime.now(TR)
    d = dt.date()
    if is_bist_holiday(d):
        return False
    open_hour, close_hour, _ = _market_hours()
    open_t = time(open_hour, 0)
    if is_bist_half_day(d):
        close_t = time(_half_day_hour(), 0)
    else:
        close_t = time(close_hour, 0)
    return open_t <= dt.time() < close_t


def bist_close_time(d: date) -> time:
    """Continuous-trading close for the given date (half-day aware).

    Callers must use this accessor so session-end logic stays single-sourced.
    """
    if is_bist_half_day(d):
        return time(_half_day_hour(), 0)
    _, close_hour, _ = _market_hours()
    return time(close_hour, 0)


def bist_session_close_time(d: date) -> time:
    """Full session close incl. the closing/single-price auction (kapanis seansi).

    Continuous trading ends at ``bist_close_time``; the closing session runs
    ~10 more minutes. EOD reconciliation must only run after this time.
    """
    _, _, buffer_min = _market_hours()
    base = datetime.combine(d, bist_close_time(d))
    return (base + timedelta(minutes=buffer_min)).time()


def bist_eod_time(d: date) -> time:
    """Earliest safe EOD reconciliation time (session close + small delay)."""
    base = datetime.combine(d, bist_session_close_time(d))
    from bist_bot.config.settings import settings

    delay = max(0, int(getattr(settings, "EOD_CLOSE_DELAY_MINUTES", 2)))
    return (base + timedelta(minutes=delay)).time()


def next_bist_session(after: datetime | None = None) -> datetime:
    if after is None:
        after = datetime.now(TR)
    d = after.date()
    if is_bist_holiday(d) or after.time() >= bist_close_time(d):
        d += timedelta(days=1)
    while is_bist_holiday(d):
        d += timedelta(days=1)
    open_hour, _, _ = _market_hours()
    return datetime.combine(d, time(open_hour, 0), tzinfo=TR)
