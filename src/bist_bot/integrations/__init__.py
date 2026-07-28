"""External service integrations.

Each integration exposes a small client class that is safe to instantiate even
when the external service is unreachable or not configured. The default
behaviour is to no-op and log a single warning, so the rest of the BIST Bot
pipeline keeps working.
"""

from bist_bot.integrations.midas import MidasClient

__all__ = ["MidasClient"]
