"""Post-close (EOD) pass verification — tek komutla günlük kontrol listesi.

Usage (repo kökünden, host tarafında):
    python scripts/check_eod_pass.py
    python scripts/check_eod_pass.py --date 2026-08-24
    python scripts/check_eod_pass.py --container bist-bot-worker --since 6h
    python scripts/check_eod_pass.py --no-docker

Kontroller:
  1. EOD pass log satırları (docker logs: scheduler_eod_close_started/completed,
     eod_close_pass_completed). Docker yoksa SKIP (exit etkilemez).
  2. results/signal_outcomes.csv: toplam kapanan, hedef günün EOD_CLOSE satırları,
     son kayıt.
  3. P5 kalibrasyon tetik durumu (reports.score_correlation.compute_p5_trigger —
     tek kaynak, aynı kural seti).
  4. Git hijyeni: results/ altında tracked dosyada değişim yok (runtime dosyalar
     #115'ten beri ignore; analiz artefaktları temiz kalmalı).

Exit: 0 = tüm kontroller PASS (log kontrolü SKIP olabildiği kabul edilir),
1 = en az biri FAIL.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bist_bot.market_calendar import TR  # noqa: E402
from bist_bot.reports.score_correlation import (  # noqa: E402
    P5_MIN_OUTCOMES,
    P5_MIN_TRADING_DAYS,
    _p5_local_tr_date,
    compute_p5_trigger,
)

# Aynısı signal_outcome_tracker.py'de (SignalOutcomeTracker.csv_path).
OUTCOME_CSV = REPO_ROOT / "results" / "signal_outcomes.csv"


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def check_eod_rows(csv_path: Path, target: date) -> dict[str, Any]:
    """Kontrol 2: hedef günün EOD_CLOSE kayıtları + genel sayılar."""
    rows = _load_rows(csv_path)
    todays_eod = [
        row
        for row in rows
        if (row.get("outcome") or "").strip() == "EOD_CLOSE" and _p5_local_tr_date(row) == target
    ]
    last = rows[-1] if rows else None
    return {
        "total_closed": len(rows),
        "todays_eod": len(todays_eod),
        "last_row": last,
    }


def check_git_hygiene(repo_root: Path) -> tuple[bool, list[str]]:
    """Kontrol 4: results/ altında tracked dosya değişimi yok mu?"""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "results/"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ["git çalıştırılamadı"]
    entries = [line for line in result.stdout.splitlines() if line.strip()]
    return (len(entries) == 0, entries)


def check_docker_logs(container: str, since: str, runner=subprocess.run) -> tuple[str, list[str]]:
    """Kontrol 1: EOD pass log satırları. Döner: ("OK"|"SKIP"|"FAIL", satırlar)."""
    try:
        result = runner(
            ["docker", "logs", "--since", since, container],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return "SKIP", []
    if result.returncode != 0:
        return "FAIL", [
            result.stderr.strip().splitlines()[-1] if result.stderr else "docker logs hatası"
        ]
    matches = [
        line
        for line in result.stdout.splitlines()
        if "eod_close" in line or "eod_outcome" in line or "scheduler_eod" in line
    ]
    return ("OK" if matches else "FAIL"), matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Hedef gün (YYYY-MM-DD, varsayılan: bugün TR)")
    parser.add_argument("--container", default="bist-bot-worker")
    parser.add_argument("--since", default="6h", help="docker logs --since (varsayılan 6h)")
    parser.add_argument("--no-docker", action="store_true", help="log kontrolünü tamamen atla")
    args = parser.parse_args(argv)

    target = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(TR).date()
    )

    print(f"=== EOD Pas Kontrolü — {target.isoformat()} (TR) ===\n")
    overall_ok = True

    # 1) Log (docker)
    if args.no_docker:
        print("[1/4] EOD log kontrolü: SKIP (--no-docker)")
    else:
        status, lines = check_docker_logs(args.container, args.since)
        label = {"OK": "PASS", "SKIP": "SKIP", "FAIL": "FAIL"}[status]
        print(f"[1/4] EOD log kontrolü: {label} ({args.container}, --since {args.since})")
        for line in lines[:5]:
            print(f"      {line}")
        if status == "FAIL":
            overall_ok = False

    # 2) Outcome satırları
    info = check_eod_rows(OUTCOME_CSV, target)
    if info["total_closed"] == 0:
        status2 = "FAIL" if (datetime.now(TR).date() >= target) else "PASS"
        detail = "signal_outcomes.csv boş — P5 veri saati henüz başlamamış mı?"
    else:
        status2 = "PASS" if info["todays_eod"] > 0 else "FAIL"
        last = info["last_row"] or {}
        detail = (
            f"toplam kapanan: {info['total_closed']} · bugün EOD_CLOSE: {info['todays_eod']} · "
            f"son: {last.get('ticker', '?')} {last.get('outcome', '?')} "
            f"@ {last.get('exit_price', '?')} ({(last.get('exit_ts') or '')[:16]})"
        )
    print(f"[2/4] Outcome CSV: {status2} — {detail}")
    if status2 == "FAIL":
        overall_ok = False

    # 3) P5 tetik durumu (tek kaynak)
    trigger = compute_p5_trigger(_load_rows(OUTCOME_CSV))
    fired_mark = "ATEŞLENDİ → kalibrasyon koşusu zorunlu" if trigger["fired"] else "hazır değil"
    print(
        f"[3/4] P5 tetik: outcome {trigger['outcomes']}/{P5_MIN_OUTCOMES} · "
        f"işlem günü {trigger['trading_days']}/{P5_MIN_TRADING_DAYS} → {fired_mark}"
    )

    # 4) Git hijyeni
    git_ok, entries = check_git_hygiene(REPO_ROOT)
    print(f"[4/4] Git hijyeni (results/): {'PASS' if git_ok else 'FAIL'}")
    for entry in entries[:5]:
        print(f"      {entry}")
    if not git_ok:
        overall_ok = False

    print(
        f"\nSonuç: {'OK — tüm kontroller geçti' if overall_ok else 'DİKKAT — üstteki FAIL maddelerine bakın'}"
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
