"""Primary application-facing data access facade."""

from bist_bot.db.repositories import AppRepository


class DataAccess(AppRepository):
    """Stable facade for signals, scan logs, and paper-trade persistence."""

    pass


__all__ = ["DataAccess"]
