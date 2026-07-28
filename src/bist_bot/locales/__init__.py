from bist_bot.locales import en, tr

DEFAULT_LOCALE = "tr"

_catalogs = {
    "tr": tr.tr,
    "en": en.en,
}


def get_message(key: str, locale: str | None = None, **kwargs) -> str:
    """Look up a translation for ``key`` in the requested locale.

    When ``locale`` is omitted, falls back to the current :data:`DEFAULT_LOCALE`.
    """
    effective_locale = locale if locale is not None else DEFAULT_LOCALE
    catalog = _catalogs.get(effective_locale, _catalogs[DEFAULT_LOCALE])
    message = catalog.get(key, _catalogs[DEFAULT_LOCALE].get(key, key))
    if kwargs:
        try:
            return message.format(**kwargs)
        except (KeyError, ValueError):
            return message
    return message


def set_default_locale(locale: str) -> None:
    global DEFAULT_LOCALE
    if locale in _catalogs:
        DEFAULT_LOCALE = locale


def get_available_locales() -> list[str]:
    return list(_catalogs.keys())
