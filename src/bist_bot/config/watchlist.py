"""Watchlist loading utilities."""

from __future__ import annotations

import csv
import os
from pathlib import Path

BIST30_TICKERS: list[str] = [
    "AKBNK.IS",
    "ARCLK.IS",
    "ASELS.IS",
    "ASTOR.IS",
    "BIMAS.IS",
    "EKGYO.IS",
    "ENKAI.IS",
    "EREGL.IS",
    "FROTO.IS",
    "GARAN.IS",
    "GUBRF.IS",
    "HEKTS.IS",
    "ISCTR.IS",
    "KCHOL.IS",
    "KONTR.IS",
    "KOZAA.IS",
    "KOZAL.IS",
    "KRDMD.IS",
    "ODAS.IS",
    "OYAKC.IS",
    "PETKM.IS",
    "PGSUS.IS",
    "SAHOL.IS",
    "SASA.IS",
    "SISE.IS",
    "TAVHL.IS",
    "TCELL.IS",
    "THYAO.IS",
    "TOASO.IS",
    "TUPRS.IS",
]


def robust_watchlist_path() -> Path:
    """Return the configured robust watchlist CSV path."""
    base = Path(__file__).resolve().parent.parent.parent.parent
    default_path = base / "results" / "robust_watchlist.csv"
    return Path(os.getenv("WATCHLIST_ROBUST_PATH", str(default_path)))


def resolve_watchlist_source(default_source: str | None = None) -> str:
    """Resolve the watchlist source name from environment variables.

    Supports 'robust', 'bist30', 'bist100', or 'file:<path>'.
    Defaults to 'robust' if not set.
    """
    source = os.getenv("WATCHLIST_SOURCE") or os.getenv("BIST_BOT_WATCHLIST_SOURCE")
    if not source:
        return default_source or "robust"
    source = source.strip()
    if source.lower().startswith("file:"):
        return source  # keep path case-sensitive
    return source.lower()


def load_watchlist(name: str = "robust") -> list[str]:
    """Load a named watchlist from CSV.

    If name starts with 'file:', loads from the specified file path.
    Otherwise, loads f"{name}_watchlist.csv" from the results directory.
    """
    base = Path(__file__).resolve().parent.parent.parent.parent
    
    if name.lower().startswith("file:"):
        path_str = name[5:].strip()
        path = Path(path_str)
        if not path.is_absolute():
            path = base / path
    else:
        if name.lower() == "robust":
            path = robust_watchlist_path()
        else:
            default_path = base / "results" / f"{name}_watchlist.csv"
            path = Path(os.getenv(f"WATCHLIST_{name.upper()}_PATH", str(default_path)))

    if not path.exists():
        # Fallback to static list if file is missing
        if name == "bist100":
            from bist_bot.data.bist100 import BIST100_TICKERS
            return list(BIST100_TICKERS)
        if name == "bist30":
            return list(BIST30_TICKERS)
        return []

    tickers: list[str] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return []
        
        first_header = header[0].strip().lower() if header else ""
        is_single_column = (
            first_header == "ticker"
            and len(header) == 1
        )

        for row in reader:
            if not row:
                continue
            ticker = row[0].strip()
            if not ticker:
                continue
            if is_single_column and "," in ticker:
                ticker = ticker.split(",", 1)[0].strip()
            tickers.append(ticker)

    return tickers
