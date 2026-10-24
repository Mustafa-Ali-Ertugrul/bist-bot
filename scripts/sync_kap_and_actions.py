"""Faz A: sync KAP disclosures and corporate actions.

KAP only exposes the current day anonymously, so run this once per trading day
(after 18:00 TR). Corporate actions come from the public İş Yatırım ratios table
(current year only).

Usage:
    python scripts/sync_kap_and_actions.py
    python scripts/sync_kap_and_actions.py --no-details
    python scripts/sync_kap_and_actions.py --actions-only --db-path data/bist.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DatabaseManager  # noqa: E402
from bist_bot.db.repositories.market_data_repository import MarketDataRepository  # noqa: E402
from bist_bot.services.corporate_actions_service import CorporateActionsService  # noqa: E402
from bist_bot.services.kap_service import KapService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync KAP disclosures and corporate actions")
    parser.add_argument("--kap-only", action="store_true", help="Skip corporate actions")
    parser.add_argument("--actions-only", action="store_true", help="Skip KAP")
    parser.add_argument(
        "--no-details", action="store_true", help="Do not fetch detail pages for unmapped titles"
    )
    parser.add_argument("--detail-limit", type=int, help="Override KAP_DETAIL_LOOKUP_LIMIT")
    parser.add_argument("--db-path", help="SQLite path (default: DATABASE_URL/DB_PATH)")
    args = parser.parse_args()

    manager = DatabaseManager(sqlite_path=args.db_path)
    manager.initialize()
    repository = MarketDataRepository(manager)
    report: dict[str, object] = {}

    if not args.actions_only:
        kap = KapService(repository, settings)
        report["kap"] = kap.sync(
            resolve_details=not args.no_details,
            max_detail_lookups=args.detail_limit,
        )
    if not args.kap_only:
        actions = CorporateActionsService(repository, settings)
        report["corporate_actions"] = actions.sync()

    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
