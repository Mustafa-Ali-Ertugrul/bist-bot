"""BIST market calendar: holiday detection, session windows, and next-session calculator.

Turkey abolished DST in 2016, so TR = UTC+3 year-round.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    import holidays as _holidays

    _TR_HOLIDAYS = _holidays.Turkey(years=range(2020, 2031))
except Exception:
    _TR_HOLIDAYS = {}

TR = timezone(timedelta(hours=3))

_MARKET_OPEN = timedelta(hours=10, minutes=0)
_MARKET_CLOSE = timedelta(hours=17, minutes=30)
_HALF_DAY_CLOSE = timedelta(hours=12, minutes=30)

_HALF_DAY_DATES: set[date] = set()


def is_bist_holiday(d: date) -> bool:
    return d.weekday() >= 5 or d in _TR_HOLIDAYS


def is_bist_half_day(d: date) -> bool:
    return d in _HALF_DAY_DATES


def is_bist_open(dt: datetime | None = None) -> bool:
    if dt is None:
        dt = datetime.now(TR)
    d = dt.date()
    if is_bist_holiday(d):
        return False
    t = dt.time()
    open_t = (datetime.min + _MARKET_OPEN).time()
    if is_bist_half_day(d):
        close_t = (datetime.min + _HALF_DAY_CLOSE).time()
    else:
        close_t = (datetime.min + _MARKET_CLOSE).time()
    return open_t <= t < close_t


def next_bist_session(after: datetime | None = None) -> datetime:
    if after is None:
        after = datetime.now(TR)
    d = after.date()
    if is_bist_holiday(d) or after.time() >= (datetime.min + _MARKET_CLOSE).time():
        d += timedelta(days=1)
    while is_bist_holiday(d):
        d += timedelta(days=1)
    return datetime.combine(d, (datetime.min + _MARKET_OPEN).time(), tzinfo=TR)
