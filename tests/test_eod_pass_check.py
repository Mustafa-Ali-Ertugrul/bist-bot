"""Tests for scripts/check_eod_pass.py (EOD pass verification tool)."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))
sys.path.insert(0, str(ROOT_DIR / "src"))

from check_eod_pass import check_docker_logs, check_eod_rows, check_git_hygiene  # noqa: E402

CSV_HEADER = ",".join(
    [
        "signal_id",
        "ticker",
        "score",
        "entry_ts",
        "side",
        "entry_price",
        "stop",
        "target",
        "exit_price",
        "exit_ts",
        "outcome",
        "holding_min",
        "mfe_pct",
        "mae_pct",
        "gross_pnl",
        "net_pnl",
    ]
)


def _write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(CSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_check_eod_rows_counts_today_eod_close(tmp_path):
    today = date(2026, 8, 24)
    rows = [
        # Bugün EOD_CLOSE (2 adet)
        "1,THYAO.IS,30,2026-08-24T07:15:00+00:00,long,5.2,5.0,5.6,5.31,2026-08-24T14:32:00+00:00,EOD_CLOSE,437,2.1,-0.5,0.02,0.015",
        "2,GUBRF.IS,28,2026-08-24T08:00:00+00:00,long,400.0,390.0,430.0,412.0,2026-08-24T14:32:00+00:00,EOD_CLOSE,412,1.0,0.0,0.03,0.025",
        # Bugün STOP_HIT (EOD sayılmaz)
        "3,DSTKF.IS,40,2026-08-24T09:00:00+00:00,long,200.0,196.0,220.0,195.9,2026-08-24T11:00:00+00:00,STOP_HIT,120,0.0,-2.0,-0.02,-0.025",
        # Dün EOD_CLOSE (bugün sayılmaz)
        "4,ASELS.IS,35,2026-08-21T07:15:00+00:00,long,300.0,295.0,330.0,305.0,2026-08-21T14:32:00+00:00,EOD_CLOSE,437,0.5,0.0,0.016,0.012",
    ]
    csv_path = _write_csv(tmp_path / "signal_outcomes.csv", rows)
    info = check_eod_rows(csv_path, today)
    assert info["total_closed"] == 4
    assert info["todays_eod"] == 2
    assert info["last_row"]["ticker"] == "ASELS.IS"


def test_check_eod_rows_missing_file(tmp_path):
    info = check_eod_rows(tmp_path / "yok.csv", date(2026, 8, 24))
    assert info["total_closed"] == 0
    assert info["todays_eod"] == 0
    assert info["last_row"] is None


def test_check_docker_logs_ok_and_fail_and_skip():
    ok_runner = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
        a,
        0,
        stdout="x scheduler_eod_close_started date=2026-08-24\ny eod_close_pass_completed\n",
        stderr="",
    )
    status, lines = check_docker_logs("c", "6h", runner=ok_runner)
    assert status == "OK"
    assert len(lines) == 2

    empty_runner = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
        a, 0, stdout="başka log\n", stderr=""
    )
    status, _ = check_docker_logs("c", "6h", runner=empty_runner)
    assert status == "FAIL"

    def broken_runner(*a, **k):
        raise FileNotFoundError("docker yok")

    status, _ = check_docker_logs("c", "6h", runner=broken_runner)
    assert status == "SKIP"


def test_check_git_hygiene_clean_and_dirty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "tracked.md").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "results/tracked.md"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], check=True
    )

    ok, entries = check_git_hygiene(tmp_path)
    assert ok and entries == []

    (tmp_path / "results" / "tracked.md").write_text("changed", encoding="utf-8")
    ok, entries = check_git_hygiene(tmp_path)
    assert not ok
    assert any("tracked.md" in e for e in entries)
