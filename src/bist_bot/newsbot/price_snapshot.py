"""Haber anı ve sonrası fiyat snapshot servisi.

Mevcut ``YFinanceProvider`` altyapısını kullanır (retry + chart API + stockanalysis
fallback zinciri hazırdır); ``.IS`` ticker normalizasyonu proje standardına uygundur
(``data/helpers.normalize_ticker`` ile aynı kural). Haber geldiğinde ``t0``,
ardından sırasıyla ``1h``/``4h``/``1d`` fiyatları ``newsbot_price_snapshots`` tablosuna
yazılır. Piyasa kapalıyken (hafta sonu / mesai dışı) snapshot alınmaz — gece haberinin
fiyat hareketi bir sonraki seans izlenimini kirletmemesi için (basit kural; bayram vb.
resmi tatil takvimi yok).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.data.fetcher import RateLimiter
from bist_bot.data.providers import YFinanceProvider
from bist_bot.newsbot.models import NewsbotPriceSnapshot

logger = get_logger("newsbot.price_snapshot", component="newsbot.price_snapshot")

IST = ZoneInfo("Europe/Istanbul")

HORIZONS = ("t0", "1h", "4h", "1d")


def normalize_ticker(symbol: str) -> str:
    """Sembolü yfinance BIST ticker'ına çevirir (THYAO -> THYAO.IS)."""
    symbol = symbol.strip().upper()
    return symbol if symbol.endswith(".IS") else f"{symbol}.IS"


def is_market_open(now: datetime | None = None) -> bool:
    """İstanbul saatine göre hafta içi 09:00-18:00 arası mı (resmi tatil kontrolü yok)."""
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return settings.server.MARKET_OPEN_HOUR <= now.hour < settings.server.MARKET_CLOSE_HOUR


def fetch_price(provider: YFinanceProvider, ticker: str) -> float | None:
    """Son işlem fiyatını 1d/1m history'nin son Close'undan döndürür."""
    df = provider.fetch_history(ticker, period="1d", interval="1m")
    if df is None or df.empty or "Close" not in df:
        return None
    return float(df["Close"].iloc[-1])


class PriceSnapshotService:
    """t0/1h/4h/1d fiyat yakalama; artık (idempotent) kayıtları atlar."""

    def __init__(
        self,
        provider: YFinanceProvider | None = None,
        fetch_price_fn=fetch_price,
    ) -> None:
        self.provider = provider or YFinanceProvider(RateLimiter())
        self.fetch_price_fn = fetch_price_fn

    def _has_snapshot(self, session: Session, article_id: int, symbol_id: int, horizon: str) -> bool:
        existing = session.execute(
            select(NewsbotPriceSnapshot.id).where(
                NewsbotPriceSnapshot.article_id == article_id,
                NewsbotPriceSnapshot.symbol_id == symbol_id,
                NewsbotPriceSnapshot.horizon == horizon,
            )
        ).scalar_one_or_none()
        return existing is not None

    def capture_t0(self, session: Session, article_id: int, symbol_id: int, symbol: str) -> bool:
        """Haber anı fiyatını kaydeder. Kayıt varsa ya da piyasa kapalıysa False."""
        if not is_market_open():
            logger.info(
                "snapshot_skipped_market_closed",
                article_id=article_id,
                symbol_id=symbol_id,
                symbol=symbol,
            )
            return False
        if self._has_snapshot(session, article_id, symbol_id, "t0"):
            return False

        ticker = normalize_ticker(symbol)
        price = self.fetch_price_fn(self.provider, ticker)
        if price is None:
            logger.warning("snapshot_fetch_failed", article_id=article_id, ticker=ticker)
            return False

        session.add(
            NewsbotPriceSnapshot(
                article_id=article_id, symbol_id=symbol_id, horizon="t0", price=price
            )
        )
        logger.info(
            "price_snapshot_captured",
            article_id=article_id,
            symbol_id=symbol_id,
            symbol=symbol,
            horizon="t0",
            price=price,
        )
        return True