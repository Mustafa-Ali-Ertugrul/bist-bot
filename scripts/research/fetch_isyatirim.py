"""Download daily market data and quarterly statements from İş Yatırım.

Per ticker (every point-in-time BIST100 member), into RESEARCH_CACHE/isy/:
- ``<CODE>_daily.json``: HisseTekil rows (adjusted + raw close, market cap PD,
  volume) 2014-01-01..today.
- ``<CODE>_fin.json``: {"YYYY/MM": {"2O": equity, "3Z": net profit YTD, ...}}
  for 2014Q1..latest, financialGroup XI_29 (industrials) or UFRS (banks).

Re-running skips files that already exist.

Usage:
    python scripts/research/fetch_isyatirim.py
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import requests

OUT = Path(os.environ.get("RESEARCH_CACHE", "tmp/research_cache")) / "isy"
PIT_FILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bist_bot"
    / "data"
    / "universe"
    / "bist100_pit_quarterly.json"
)
BASE = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx"
ITEMS = ("2O", "3Z", "3C", "3H", "1BL")
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, params: dict) -> list[dict]:
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.ok:
                payload = r.json()
                return payload.get("value") or []
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (attempt + 1))
    return []


def _published(year: int, month: int) -> bool:
    avail_month, avail_year = {3: (6, year), 6: (9, year), 9: (12, year), 12: (4, year + 1)}[month]
    return date(avail_year, avail_month, 15) <= date.today()


def fetch_daily(code: str) -> list[dict]:
    today = date.today().strftime("%d-%m-%Y")
    return _get(
        f"{BASE}/HisseTekil", {"hisse": code, "startdate": "01-01-2014", "enddate": today}
    )


def fetch_statements(code: str) -> dict[str, dict[str, float]]:
    # Only quarters whose statements are published: a chunk containing an
    # unpublished period comes back empty for the whole request.
    quarters = [(y, m) for y in range(2014, date.today().year + 1) for m in (3, 6, 9, 12)]
    quarters = [q for q in quarters if _published(*q)]
    # The endpoint rejects requests with fewer than 4 periods: chunk from the
    # newest quarter backward and pad the oldest chunk by repeating its first.
    newest_first = quarters[::-1]
    chunks = [newest_first[i : i + 4] for i in range(0, len(newest_first), 4)]
    chunks[-1] = (chunks[-1] * 4)[:4]
    out: dict[str, dict[str, float]] = {}
    for group in ("XI_29", "UFRS"):
        for chunk in chunks:
            params = {"companyCode": code, "exchange": "TRY", "financialGroup": group}
            for j, (y, m) in enumerate(chunk, start=1):
                params[f"year{j}"], params[f"period{j}"] = y, m
            rows = _get(f"{BASE}/MaliTablo", params)
            for row in rows:
                if row.get("itemCode") not in ITEMS:
                    continue
                for j, (y, m) in enumerate(chunk, start=1):
                    val = row.get(f"value{j}")
                    if val not in (None, "", "0"):
                        out.setdefault(f"{y}/{m:02d}", {})[row["itemCode"]] = float(val)
            time.sleep(0.3)
        if out:
            break
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    quarters = json.loads(PIT_FILE.read_text(encoding="utf-8"))["quarters"]
    codes = sorted({t.removesuffix(".IS") for t in set().union(*quarters.values())})
    print(f"{len(codes)} codes", flush=True)

    def one(code: str) -> str:
        daily_path, fin_path = OUT / f"{code}_daily.json", OUT / f"{code}_fin.json"
        if not daily_path.exists():
            daily_path.write_text(json.dumps(fetch_daily(code)), encoding="utf-8")
        if not fin_path.exists():
            fin_path.write_text(json.dumps(fetch_statements(code)), encoding="utf-8")
        return code

    with ThreadPoolExecutor(max_workers=6) as pool:
        for code in pool.map(one, codes):
            print("ok", code, flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
