"""Point-in-time universe resolution helpers for backtests."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from bist_bot.data.bist100 import BIST100_TICKERS
from bist_bot.data.helpers import clean_ticker_list

logger = logging.getLogger(__name__)

UNIVERSE_DIR = Path(__file__).resolve().parent / "universe"


def _coerce_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _load_snapshot(snapshot_path: Path) -> list[str]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    members = payload.get("members", [])
    return clean_ticker_list([str(member) for member in members])


def get_universe_for_date(
    as_of: date | datetime | str, current_universe: list[str] | None = None
) -> list[str]:
    target_date = _coerce_date(as_of)
    fallback = clean_ticker_list(current_universe or BIST100_TICKERS)

    candidates: list[tuple[date, Path]] = []
    for snapshot_path in sorted(UNIVERSE_DIR.glob("bist100_*.json")):
        try:
            snapshot_date = date.fromisoformat(snapshot_path.stem.removeprefix("bist100_"))
        except ValueError:
            continue
        if snapshot_date <= target_date:
            candidates.append((snapshot_date, snapshot_path))

    if not candidates:
        logger.warning(
            "Historical universe snapshot missing for %s; falling back to current universe",
            target_date.isoformat(),
        )
        return fallback

    snapshot_date, snapshot_path = candidates[-1]
    members = _load_snapshot(snapshot_path)
    logger.info(
        "Historical universe resolved for %s using snapshot %s (%s tickers)",
        target_date.isoformat(),
        snapshot_date.isoformat(),
        len(members),
    )
    return members or fallback


__all__ = ["UNIVERSE_DIR", "get_universe_for_date"]
