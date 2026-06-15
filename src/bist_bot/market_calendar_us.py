"""US market calendar using exchange_calendars (NYSE).

DST-safe: all logic delegates to exchange_calendars XNYS calendar.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

_US_EASTERN = ZoneInfo("America/New_York")


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_US_EASTERN).astimezone(ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))


def is_us_market_holiday(d: datetime | None = None) -> bool:
    nyse = xcals.get_calendar("XNYS")
    if d is None:
        d = datetime.now(_US_EASTERN)
    ts = pd.Timestamp(d.date())
    return ts not in nyse.schedule.index


def is_us_market_open(dt: datetime | None = None) -> bool:
    nyse = xcals.get_calendar("XNYS")
    if dt is None:
        dt = datetime.now(_US_EASTERN)
    ts = pd.Timestamp(dt)
    return nyse.is_open_at_time(ts)


def next_us_session(after: datetime | None = None) -> datetime:
    nyse = xcals.get_calendar("XNYS")
    if after is None:
        after = datetime.now(_US_EASTERN)
    ts = pd.Timestamp(after.date())
    next_session = nyse.next_open(ts)
    open_time = nyse.schedule.loc[next_session, "open"]
    if isinstance(open_time, pd.Timestamp):
        return open_time.to_pydatetime().astimezone(_US_EASTERN)
    open_dt = pd.Timestamp(open_time, tz="UTC").to_pydatetime()
    return open_dt.astimezone(_US_EASTERN)