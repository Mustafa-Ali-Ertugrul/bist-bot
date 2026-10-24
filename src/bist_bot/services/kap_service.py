"""Faz A1: store KAP disclosures and match them to BIST symbols.

KAP returns the legal company title, not the ticker. The matcher normalises
Turkish characters and removes legal suffixes first; anything still ambiguous is
left unmapped rather than guessed. Unmapped rows can be resolved from the
disclosure detail page (which carries ``stockCode``), and the result is reused on
later runs because the company title repeats every day.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import requests

from bist_bot.config.settings import settings as default_settings
from bist_bot.data.kap import KapDisclosure, fetch_disclosures, fetch_stock_code
from bist_bot.db.repositories.market_data_repository import Instrument, MarketDataRepository
from bist_bot.market_calendar import is_bist_holiday

if TYPE_CHECKING:
    from bist_bot.services.corporate_actions_service import CorporateActionsService

LEGAL_SUFFIXES = {
    "A",
    "S",
    "O",
    "AS",
    "AO",
    "TAS",
    "ANONIM",
    "ORTAKLIGI",
    "SIRKETI",
    "LIMITED",
    "LTD",
}
WEAK_TOKENS = {
    "TICARET",
    "SANAYI",
    "VE",
    "TURKIYE",
    "HOLDING",
    "GRUP",
    "GRUBU",
    "BANKASI",
    "BANKA",
}
_SPACES = re.compile(r"[^A-Z0-9]+")


def _ascii_upper(value: str) -> str:
    text = value.replace("İ", "I").replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.upper()


def normalize_company_name(value: str) -> str:
    """Upper-case ASCII tokens without legal suffixes (``TÜRK HAVA YOLLARI``)."""
    tokens = [token for token in _SPACES.split(_ascii_upper(value or "")) if token]
    kept = [token for token in tokens if token not in LEGAL_SUFFIXES]
    return " ".join(kept)


def core_company_name(value: str) -> str:
    """Normalised name without weak generic words (used as a second-chance key)."""
    tokens = normalize_company_name(value).split()
    return " ".join(token for token in tokens if token not in WEAK_TOKENS)


@dataclass
class TickerMatcher:
    """Deterministic title -> symbol matcher built from the stored universe."""

    full: dict[str, list[str]]
    core: dict[str, list[str]]

    @classmethod
    def build(cls, instruments: list[Instrument]) -> TickerMatcher:
        full: dict[str, list[str]] = {}
        core: dict[str, list[str]] = {}
        for instrument in instruments:
            full_key = normalize_company_name(instrument.name)
            core_key = core_company_name(instrument.name)
            if full_key:
                full.setdefault(full_key, []).append(instrument.code)
            if core_key:
                core.setdefault(core_key, []).append(instrument.code)
        return cls(full=full, core=core)

    def match(self, title: str) -> str | None:
        full_key = normalize_company_name(title)
        if not full_key:
            return None
        candidates = self.full.get(full_key)
        if candidates and len(set(candidates)) == 1:
            return candidates[0]

        core_key = core_company_name(title)
        candidates = self.core.get(core_key) if core_key else None
        if candidates and len(set(candidates)) == 1 and len(core_key.split()) >= 2:
            return candidates[0]

        title_tokens = set(full_key.split())
        contained: set[str] = set()
        for key, codes in self.full.items():
            key_tokens = set(key.split())
            if len(key_tokens) < 2:
                continue
            if key_tokens <= title_tokens:
                contained.update(codes)
        if len(contained) == 1:
            return next(iter(contained))
        return None


class KapService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
        *,
        fetch: Callable[..., list[KapDisclosure]] = fetch_disclosures,
        detail_fetch: Callable[..., str | None] = fetch_stock_code,
        session: requests.Session | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings
        self._fetch = fetch
        self._detail_fetch = detail_fetch
        self._session = session or requests.Session()

    # ------------------------------------------------------------------
    def _known_titles(self) -> dict[str, str]:
        return self.repository.kap_title_map()

    def _instrument_ticker(self, code: str | None) -> str | None:
        """Store the same ``THYAO.IS`` ticker form as the bars and actions tables."""
        if not code:
            return None
        instrument = self.repository.get_instrument(code)
        return instrument.ticker if instrument else None

    def sync(
        self, *, resolve_details: bool = True, max_detail_lookups: int | None = None
    ) -> dict[str, int]:
        disclosures = self._fetch(self._session)
        if not disclosures:
            return {"fetched": 0, "inserted": 0, "updated": 0, "mapped": 0, "unmapped": 0}

        matcher = TickerMatcher.build(self.repository.list_active_instruments())
        known = self._known_titles()
        budget = (
            max(0, int(max_detail_lookups))
            if max_detail_lookups is not None
            else max(0, int(getattr(self.settings, "KAP_DETAIL_LOOKUP_LIMIT", 50)))
        )
        rows: list[dict[str, object]] = []
        mapped = 0
        for item in disclosures:
            ticker = known.get(item.company_title) or matcher.match(item.company_title)
            if ticker is None and resolve_details and budget > 0:
                budget -= 1
                ticker = self._detail_fetch(item.disclosure_index, self._session)
            ticker = self._instrument_ticker(ticker)
            if ticker:
                mapped += 1
            rows.append(
                {
                    "disclosure_index": item.disclosure_index,
                    "ticker": ticker,
                    "company_title": item.company_title,
                    "subject": item.subject,
                    "summary": item.summary,
                    "disclosure_class": item.disclosure_class,
                    "published_at": item.published_at,
                    "published_date": item.published_date,
                    "url": item.url,
                }
            )
        result = self.repository.upsert_kap_disclosures(rows)
        return {
            "fetched": len(disclosures),
            "inserted": result["inserted"],
            "updated": result["updated"],
            "mapped": mapped,
            "unmapped": len(disclosures) - mapped,
        }

    def disclosures(self, code: str, *, limit: int = 20) -> list[dict[str, object]] | None:
        instrument = self.repository.get_instrument(code)
        if instrument is None:
            return None
        return self.repository.list_kap_disclosures(instrument.ticker, limit=limit)


class KapSyncJob:
    """Daily KAP + corporate-action refresh, run by the worker after the close.

    Kept separate from the screen job because the scores and the dividend-yield
    screen read these tables; refreshing them first keeps the day consistent.
    """

    def __init__(
        self,
        kap: KapService,
        actions: CorporateActionsService,
        settings: Any | None = None,
    ) -> None:
        self.kap = kap
        self.actions = actions
        self.settings = settings or default_settings
        self._last_run_date: date | None = None

    def run_if_due(self, now: datetime) -> bool:
        if not bool(getattr(self.settings, "KAP_SYNC_ENABLED", False)):
            return False
        today = now.date()
        if self._last_run_date == today:
            return False
        if is_bist_holiday(today):
            return False
        if now.hour < int(getattr(self.settings, "KAP_SYNC_HOUR_TR", 18)):
            return False

        from bist_bot.app_logging import get_logger

        logger = get_logger(__name__)
        kap_report = self.kap.sync()
        action_report = self.actions.sync()
        self._last_run_date = today
        logger.info(
            "kap_sync_completed",
            disclosures=kap_report.get("fetched", 0),
            mapped=kap_report.get("mapped", 0),
            actions=action_report.get("written", 0),
        )
        return True


__all__ = [
    "KapService",
    "KapSyncJob",
    "TickerMatcher",
    "core_company_name",
    "normalize_company_name",
]
