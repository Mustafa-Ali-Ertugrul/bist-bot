"""Legacy compatibility wrapper for the modular repository layer."""

from bist_bot.db import DataAccess


class SignalDatabase(DataAccess):
    """Backward-compatible alias for older imports expecting `SignalDatabase`."""

    pass


__all__ = ["SignalDatabase"]
