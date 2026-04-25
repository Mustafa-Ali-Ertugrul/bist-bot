"""Deprecated shim — use ``bist_bot.risk`` instead.

.. deprecated::
    Import from :mod:`bist_bot.risk` directly::

        from bist_bot.risk import RiskManager, RiskLevels
"""

import warnings

from bist_bot.risk.manager import RiskManager
from bist_bot.risk.models import RiskLevels

__all__ = ["RiskLevels", "RiskManager"]

warnings.warn(
    "bist_bot.risk_manager is deprecated; use 'from bist_bot.risk import RiskManager, RiskLevels' instead.",
    DeprecationWarning,
    stacklevel=2,
)
