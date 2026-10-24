"""Faz A2: dividends and capital actions, plus the trailing dividend yield.

Data comes from the public İş Yatırım "Temel Değerler" page (current year). The
yield is a gross trailing-12-month figure: cash dividend per share divided by the
latest close. It is published as information, never as a recommendation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import requests

from bist_bot.config.settings import settings as default_settings
from bist_bot.data.isyatirim import fetch_corporate_actions
from bist_bot.db.repositories.market_data_repository import MarketDataRepository

KIND_LABELS = {
    "temettu": "Nakit temettü",
    "bedelsiz": "Bedelsiz sermaye artırımı",
    "bedelli": "Bedelli sermaye artırımı",
}


class CorporateActionsService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
        *,
        fetch: Callable[..., list[dict[str, object]]] = fetch_corporate_actions,
        session: requests.Session | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings
        self._fetch = fetch
        self._session = session or requests.Session()

    # ------------------------------------------------------------------
    def sync(self) -> dict[str, int]:
        rows = self._fetch(self._session)
        if not rows:
            return {"fetched": 0, "written": 0}
        return {"fetched": len(rows), "written": self.repository.upsert_corporate_actions(rows)}

    def actions(self, code: str) -> list[dict[str, object]] | None:
        instrument = self.repository.get_instrument(code)
        if instrument is None:
            return None
        rows = self.repository.list_corporate_actions(instrument.ticker)
        for row in rows:
            row["kind_label"] = KIND_LABELS.get(str(row["kind"]), str(row["kind"]))
        return rows

    def trailing_dividend(self, code: str, *, days: int = 365) -> dict[str, float | None] | None:
        """Gross cash dividend of the last ``days`` and its yield on the latest close."""
        instrument = self.repository.get_instrument(code)
        if instrument is None:
            return None
        start = date.today() - timedelta(days=days)
        bars = self.repository.get_bars(instrument.ticker)
        last_close = bars[-1].close if bars else None
        rows = self.repository.list_corporate_actions(instrument.ticker, since=start)
        per_share = sum(
            float(row["cash_per_share_tl"] or 0.0) for row in rows if row["kind"] == "temettu"
        )
        yield_pct = None
        if last_close and last_close > 0 and per_share > 0:
            yield_pct = round(per_share / last_close * 100.0, 2)
        return {
            "cash_per_share_tl": round(per_share, 4) if per_share else None,
            "yield_pct": yield_pct,
            "window_days": float(days),
        }


__all__ = ["KIND_LABELS", "CorporateActionsService"]
