from config.settings import Settings, settings

__all__ = ["Settings", "settings"]


def __getattr__(name: str):
    return getattr(settings, name)
