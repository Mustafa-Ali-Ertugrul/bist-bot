from dataclasses import dataclass

from config.settings import Settings, settings as _base_settings


@dataclass
class BotSettings:
    rsi_oversold: int = _base_settings.RSI_OVERSOLD
    rsi_overbought: int = _base_settings.RSI_OVERBOUGHT
    adx_threshold: int = _base_settings.ADX_THRESHOLD
    scan_interval: int = _base_settings.SCAN_INTERVAL_MINUTES
    paper_mode: bool = _base_settings.PAPER_MODE
    telegram_min_score: int = _base_settings.TELEGRAM_MIN_SCORE
    RATE_LIMIT_SECONDS: float = _base_settings.RATE_LIMIT_SECONDS

    def __getattr__(self, name: str):
        return getattr(_base_settings, name)


settings = BotSettings()

__all__ = ["Settings", "settings"]


def __getattr__(name: str):
    return getattr(settings, name)
