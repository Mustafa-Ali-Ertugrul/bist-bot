"""Parse Borsa İstanbul quarterly "BIST Pay Endeksleri" change announcements.

Input: a directory of saved announcement pages (``<announcement_id>.html``),
e.g. downloaded from https://www.borsaistanbul.com/node/<id> (the node URL
redirects to the announcement). Output: the BIST 100 added/removed codes per
period, merged into ``changes.json`` next to this script.

Hand-verified corrections live in ``overrides.json`` (malformed tables, and
2025 Q1 whose page is empty on the exchange site).

Usage:
    python scripts/research/bist100_pit/parse_announcements.py tmp/research_cache/announcements
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CODE = re.compile(r"[A-Z][A-Z0-9]{2,5}")
PERIOD = re.compile(r"(\d{2})[./](\d{2})[./](\d{4})\s*-\s*\d{2}[./]\d{2}[./]\d{4}")


def _period_start(text: str) -> str | None:
    m = PERIOD.search(text)
    if not m:
        return None
    year, month = int(m.group(3)), int(m.group(2))
    quarter = (month - 1) // 3 + 1
    return f"{year}-{3 * (quarter - 1) + 1:02d}-01"


def parse(path: Path) -> tuple[str | None, list[str], list[str]]:
    s = path.read_text(encoding="utf-8")
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)))
    # BIST 100 table = first table after the "BIST 100 ENDEKSİ" heading
    # (newer pages list BIST 30 first).
    masked = re.sub(r"<[^>]+>", lambda m: " " * len(m.group(0)), s).upper().replace("İ", "I")
    marker = re.search(r"BIST\s*100\s*ENDEKS", masked)
    blocks = [(m.start(), m.group(0)) for m in re.finditer(r"<table.*?</table>", s, re.S | re.I)]
    if marker:
        blocks = [b for b in blocks if b[0] > marker.start()]
    for _, block in blocks:
        try:
            tables = pd.read_html(io.StringIO(block))
        except ValueError:
            continue
        for t in tables:
            header = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
            first = [str(x) for x in t.iloc[0]]
            labels = [(h + " " + f).upper() for h, f in zip(header, first, strict=True)]
            if not any("ALINACAK" in label for label in labels):
                continue

            def grab(key: str, t=t, labels=labels) -> list[str]:
                cols = [i for i, label in enumerate(labels) if key in label]

                def codes(i: int) -> list[str]:
                    return [
                        str(v).strip()
                        for v in t.iloc[:, i].dropna()
                        if CODE.fullmatch(str(v).strip())
                    ]

                if not cols:
                    return []
                best = max(cols, key=lambda i: (len(codes(i)), -i))
                return list(dict.fromkeys(codes(best)))

            return _period_start(text), grab("ALINACAK"), grab("IKARILACAK")
    raise ValueError(f"BIST 100 table not found in {path.name}")


def main(html_dir: str) -> None:
    overrides = json.loads((HERE / "overrides.json").read_text(encoding="utf-8"))
    out_path = HERE / "changes.json"
    existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    by_period = {row["period_start"]: row for row in existing}
    for path in sorted(Path(html_dir).glob("*.html")):
        ann_id = path.stem
        try:
            start, added, removed = parse(path)
        except ValueError:
            start, added, removed = None, [], []
        if ann_id in overrides:
            start = overrides[ann_id].get("start", start)
            added, removed = overrides[ann_id]["added"], overrides[ann_id]["removed"]
        if not start or len(added) != len(removed) or not added:
            print(f"skip {ann_id}: start={start} added={len(added)} removed={len(removed)}")
            continue
        by_period[start] = {
            "announcement_id": ann_id,
            "period_start": start,
            "added": added,
            "removed": removed,
        }
    rows = sorted(by_period.values(), key=lambda r: r["period_start"])
    out_path.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} periods -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1])
