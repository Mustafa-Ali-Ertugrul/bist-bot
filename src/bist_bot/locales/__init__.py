from bist_bot.locales import en, tr

DEFAULT_LOCALE = "tr"

_catalogs = {
    "tr": tr.tr,
    "en": en.en,
}


def get_message(key: str, locale: str = DEFAULT_LOCALE, **kwargs) -> str:
    catalog = _catalogs.get(locale, _catalogs[DEFAULT_LOCALE])
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
