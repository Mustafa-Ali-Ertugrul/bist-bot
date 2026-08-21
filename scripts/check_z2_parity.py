"""Z2 parity check: walk-forward A/B between the pre-Z2 and post-Z2 commits.

Z2 (volatility-adaptive stop/target) only touches the LIVE risk path
(`risk/stops.py::determine_final_levels`). The backtest path is deliberately
separate (see results/stop_target_parity.md), so the BIST30 walk-forward
output must be BIT-IDENTICAL between the two commits when both runs consume
the same OHLCV cache (default cache is HOME-based: ~/.cache/bist_bot/wf_data).

Usage (from repo root, with a clean working tree and network access):
    python scripts/check_z2_parity.py
    python scripts/check_z2_parity.py --limit 5          # quick smoke
    python scripts/check_z2_parity.py --force-download    # ignore cache for both runs

Behavior:
    1. Records the current branch/commit, checks out the BEFORE commit (detached),
       runs the walk-forward -> results/z2_parity_before.csv
    2. Checks out the AFTER commit, runs again (same cache) -> results/z2_parity_after.csv
    3. Always restores the original branch/commit (even on failure)
    4. Compares the two CSVs ticker-by-ticker, column-by-column
    5. Writes results/z2_parity_check.md (filled template) and exits 0 on PASS
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WALK_FORWARD = REPO_ROOT / "scripts" / "run_walk_forward_bist30.py"
BEFORE_CSV = REPO_ROOT / "results" / "z2_parity_before.csv"
AFTER_CSV = REPO_ROOT / "results" / "z2_parity_after.csv"
REPORT_MD = REPO_ROOT / "results" / "z2_parity_check.md"
FLOAT_EPS = 1e-9


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_raw(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _run_walk_forward(label: str, output_csv: Path, extra_args: list[str]) -> None:
    cmd = [sys.executable, str(WALK_FORWARD), "--output", str(output_csv), *extra_args]
    # Make the repo importable even when `bist_bot` is not pip-installed in the venv.
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    ).rstrip(os.pathsep)
    print(f"\n[{label}] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        raise SystemExit(f"[{label}] walk-forward failed (exit {result.returncode})")
    if not output_csv.exists():
        raise SystemExit(f"[{label}] expected output missing: {output_csv}")
    print(f"[{label}] wrote {output_csv}")


def _load_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["ticker"]: row for row in csv.DictReader(fh)}


def _compare(before: dict, after: dict) -> list[str]:
    """Return a list of delta descriptions (empty list == identical)."""
    deltas: list[str] = []
    for ticker in sorted(set(before) | set(after)):
        b = before.get(ticker)
        a = after.get(ticker)
        if b is None or a is None:
            deltas.append(f"{ticker}: row present only in {'after' if b is None else 'before'}")
            continue
        for column in b:
            if column == "ticker":
                continue
            b_raw = (b.get(column) or "").strip()
            a_raw = (a.get(column) or "").strip()
            if b_raw == a_raw:
                continue
            try:
                b_val = float(b_raw)
                a_val = float(a_raw)
                if abs(b_val - a_val) <= FLOAT_EPS:
                    continue
                deltas.append(f"{ticker}.{column}: {b_raw} -> {a_raw} (delta {a_val - b_val:+.6f})")
            except ValueError:
                deltas.append(f"{ticker}.{column}: '{b_raw}' -> '{a_raw}' (non-numeric)")
    return deltas


def _write_report(before_ref: str, after_ref: str, deltas: list[str], duration_s: float) -> None:
    stamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    verdict = "PASS — delta=0 (beklenen: Z2 yalnızca canlı risk yolunu değiştirir)" if not deltas else (
        "FAIL — walk-forward çıktısında fark var; kök nedene bakılmalı"
    )
    lines = [
        "# Z2 Parity Check — Walk-Forward A/B",
        "",
        f"- **Koşu zamanı (UTC±):** {stamp}",
        f"- **Before commit:** `{before_ref}` (Z2 öncesi, 300723d hattı)",
        f"- **After commit:** `{after_ref}` (Z2 sonrası)",
        f"- **Süre:** {duration_s:.0f} sn",
        "- **Veri:** Aynı OHLCV cache'i (`~/.cache/bist_bot/wf_data`) — iki koşu bit-identical fiyatlara bakar",
        f"- **Sonuç:** {verdict}",
        "",
        "## Farklar",
        "",
    ]
    if deltas:
        lines.extend(f"- {d}" for d in deltas)
    else:
        lines.append("Fark yok: tüm ticker × tüm kolon değerleri identik.")
    lines.extend(
        [
            "",
            "## Yorum",
            "",
            "Z2, `risk/stops.py::determine_final_levels` (canlı yol) üzerindedir; backtest",
            "motoru vektörel stop/target'ı kendisi üretir (ayrık sözleşme,",
            "`results/stop_target_parity.md`). Bu nedenle walk-forward çıktısının",
            "değişmemesi **beklenen** sonuçtur. Fark görülürse: (1) cache paylaşımı bozulmuş",
            "olabilir (--force-download ile iki koşuya da taze veri alın), (2) Z2 commit'i",
            "backtest yoluna sızdırma yapmış olabilir — diff'lenmesi gerekir.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRapor yazıldı: {REPORT_MD}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-commit", default="300723d", help="Z2 öncesi commit")
    parser.add_argument("--after-commit", default="10a630e", help="Z2 sonrası commit")
    parser.add_argument("--limit", type=int, default=0, help="Yalnızca ilk N ticker (0 = tüm BIST30)")
    parser.add_argument("--period", default="3y", help="yfinance period (default: 3y)")
    parser.add_argument(
        "--force-download", action="store_true", help="İki koşuda da cache'i yok say"
    )
    args = parser.parse_args(argv)

    # Untracked files are harmless for checkout; tracked modifications are not.
    status = _git_raw("status", "--porcelain", "--untracked-files=no")
    if status.stdout.strip():
        raise SystemExit(
            "Çalışma ağacında modifiye EDİLMİŞ tracked dosyalar var — önce commit/stash yap "
            "(parity koşusu checkout değiştirir; untracked dosyalar engel değildir)."
        )
    original_ref = _git("rev-parse", "--abbrev-ref", "HEAD")
    original_sha = _git("rev-parse", "HEAD")
    print(f"Özgü nokta: {original_ref} ({original_sha}) — bitişte geri dönülecek.")

    extra = ["--limit", str(args.limit), "--period", args.period]
    if args.force_download:
        extra.append("--force-download")

    started = datetime.now(UTC)
    try:
        print(f"\n=== BEFORE: {_git('rev-parse', args.before_commit)} ===")
        _git("checkout", "--detach", args.before_commit)
        _run_walk_forward("BEFORE", BEFORE_CSV, extra)

        print(f"\n=== AFTER: {_git('rev-parse', args.after_commit)} ===")
        _git("checkout", "--detach", args.after_commit)
        _run_walk_forward("AFTER", AFTER_CSV, extra)
    finally:
        _git("checkout", original_ref)
        restored = _git("rev-parse", "HEAD")
        if restored != original_sha:
            raise SystemExit(f"Branch restore başarısız! HEAD={restored}, beklenen={original_sha}")
        print(f"\nGeri dönüldü: {original_ref} ({restored})")

    before = _load_rows(BEFORE_CSV)
    after = _load_rows(AFTER_CSV)
    print(f"\nKarşılaştırma: {len(before)} ticker (before) x {len(after)} ticker (after)")
    deltas = _compare(before, after)
    duration = (datetime.now(UTC) - started).total_seconds()
    _write_report(_git("rev-parse", args.before_commit), _git("rev-parse", args.after_commit), deltas, duration)

    if deltas:
        print(f"\n❌ FAIL — {len(deltas)} fark bulundu:")
        for d in deltas[:20]:
            print(f"  - {d}")
        return 1
    print(f"\n✅ PASS — {len(before)} ticker, tüm kolonlar identik (delta=0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
