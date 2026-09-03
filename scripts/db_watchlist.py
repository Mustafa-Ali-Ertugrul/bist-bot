from bist_bot.config.settings import settings
from bist_bot.config.watchlist import load_watchlist

print("WATCHLIST_SOURCE:", settings.WATCHLIST_SOURCE)
wl = load_watchlist(settings.WATCHLIST_SOURCE)
print("watchlist len:", len(wl))
print("first 10:", wl[:10])
