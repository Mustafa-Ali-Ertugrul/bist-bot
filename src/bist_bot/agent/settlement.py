from datetime import date, datetime, timedelta

from bist_bot.market_calendar import is_bist_holiday


def settlement_date(trade_date: date, days: int = 2) -> date:
    result = trade_date
    days_added = 0
    while days_added < days:
        result = result + timedelta(days=1)
        if result.weekday() < 5 and not is_bist_holiday(result):
            days_added += 1
    return result


def is_settled(trade_date: date, current_date: date, days: int = 2) -> bool:
    return current_date >= settlement_date(trade_date, days)


def calculate_settlement(entry_time: datetime, days: int = 2) -> datetime:
    return datetime.combine(settlement_date(entry_time.date(), days), entry_time.time())
