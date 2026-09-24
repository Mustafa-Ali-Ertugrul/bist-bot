"""Reconstruct point-in-time BIST 100 membership per quarter.

Anchor: ``src/bist_bot/data/universe/bist100_2024-01-01.json``. Despite its
file name, its member list is the 2026 Q1 (01.01.2026-31.03.2026) composition:
every 2026 Q2 addition is absent from it and every 2026 Q2 removal is present.
From the anchor we walk backward (prev = cur - added + removed) and forward
(next = cur - removed + added) through ``changes.json``.

Known limitation: intra-quarter replacements (mergers, market transfers) are
not in the quarterly announcements, so some quarters carry up to ~6 extra
members; each inconsistency is printed.

Usage:
    python scripts/research/bist100_pit/build_pit_universe.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
UNIVERSE_DIR = REPO / "src" / "bist_bot" / "data" / "universe"
ANCHOR_FILE = UNIVERSE_DIR / "bist100_2024-01-01.json"
ANCHOR_PERIOD = "2026-01-01"
OUT_FILE = UNIVERSE_DIR / "bist100_pit_quarterly.json"
# Codes that changed; yfinance only serves history under the new code.
RENAMES = {"IPEKE": "TRENJ", "YAZIC": "AGHOL"}


def build() -> dict[str, list[str]]:
    changes = json.loads((HERE / "changes.json").read_text(encoding="utf-8"))
    by_period = {row["period_start"]: row for row in changes}
    periods = sorted(by_period)
    anchor = json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))["members"]
    anchor_set = {m.removesuffix(".IS") for m in anchor}

    members: dict[str, set[str]] = {ANCHOR_PERIOD: set(anchor_set)}
    cur = set(anchor_set)
    for i in range(periods.index(ANCHOR_PERIOD), 0, -1):
        row = by_period[periods[i]]
        added, removed = set(row["added"]), set(row["removed"])
        if added - cur or removed & cur:
            print(
                f"{periods[i]}: added-not-member={sorted(added - cur)} removed-still-member={sorted(removed & cur)}"
            )
        cur = (cur - added) | removed
        members[periods[i - 1]] = set(cur)
    cur = set(anchor_set)
    for period in periods[periods.index(ANCHOR_PERIOD) + 1 :]:
        row = by_period[period]
        added, removed = set(row["added"]), set(row["removed"])
        if added & cur or removed - cur:
            print(
                f"{period}: added-already-member={sorted(added & cur)} removed-not-member={sorted(removed - cur)}"
            )
        cur = (cur - removed) | added
        members[period] = set(cur)

    def canon(code: str) -> str:
        return RENAMES.get(code, code) + ".IS"

    return {p: sorted({canon(c) for c in members[p]}) for p in sorted(members)}


def main() -> None:
    quarters = build()
    payload = {
        "description": (
            "Point-in-time BIST 100 membership by quarter start, reconstructed from "
            "Borsa Istanbul quarterly periodic-change announcements "
            "(scripts/research/bist100_pit)."
        ),
        "built": date.today().isoformat(),
        "anchor": {"file": ANCHOR_FILE.name, "period_start": ANCHOR_PERIOD},
        "renames": RENAMES,
        "known_gaps": (
            "Intra-quarter replacements are not tracked (up to ~6 extra members in "
            "some quarters). Add each new quarter to changes.json and rebuild."
        ),
        "quarters": quarters,
    }
    OUT_FILE.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sizes = sorted({len(v) for v in quarters.values()})
    print(
        f"{len(quarters)} quarters ({min(quarters)}..{max(quarters)}), sizes {sizes} -> {OUT_FILE}"
    )


if __name__ == "__main__":
    main()
