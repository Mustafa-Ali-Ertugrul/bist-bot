"""Score correlation report tests (Z3)."""

import csv
from pathlib import Path

from bist_bot.reports.score_correlation import compute_stats, load_outcomes, run


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
        w.writeheader()
        w.writerows(rows)


def test_bucket_stats_known(tmp_path):
    csv_path = tmp_path / "signal_outcomes.csv"
    rows = [
        {
            "signal_id": 1,
            "ticker": "THYAO.IS",
            "score": 26,
            "entry_ts": "2026-08-20T10:00:00+00:00",
            "side": "long",
            "entry_price": 100,
            "stop": 95,
            "target": 110,
            "exit_price": 108,
            "exit_ts": "2026-08-20T11:00:00+00:00",
            "outcome": "TARGET_HIT",
            "holding_min": 60,
            "mfe_pct": 8,
            "mae_pct": -1,
            "gross_pnl": 80,
            "net_pnl": 70,
        },
        {
            "signal_id": 2,
            "ticker": "GARAN.IS",
            "score": 32,
            "entry_ts": "2026-08-20T10:00:00+00:00",
            "side": "long",
            "entry_price": 50,
            "stop": 48,
            "target": 55,
            "exit_price": 49,
            "exit_ts": "2026-08-20T11:00:00+00:00",
            "outcome": "STOP_HIT",
            "holding_min": 60,
            "mfe_pct": 2,
            "mae_pct": -2,
            "gross_pnl": -10,
            "net_pnl": -12,
        },
        {
            "signal_id": 3,
            "ticker": "ASELS.IS",
            "score": 36,
            "entry_ts": "2026-08-20T12:00:00+00:00",
            "side": "long",
            "entry_price": 80,
            "stop": 78,
            "target": 88,
            "exit_price": 85,
            "exit_ts": "2026-08-20T13:00:00+00:00",
            "outcome": "TARGET_HIT",
            "holding_min": 60,
            "mfe_pct": 6,
            "mae_pct": -1,
            "gross_pnl": 50,
            "net_pnl": 45,
        },
    ]
    _write_csv(csv_path, rows)
    loaded = load_outcomes(csv_path)
    stats = compute_stats(loaded)
    assert stats["bucket_stats"]["25-30"]["count"] == 1
    assert stats["bucket_stats"]["30-35"]["count"] == 1
    assert stats["bucket_stats"]["35-40"]["count"] == 1
    assert stats["bucket_stats"]["25-30"]["win_rate"] == 100.0
    assert stats["bucket_stats"]["30-35"]["win_rate"] == 0.0


def test_small_n_warning(tmp_path):
    csv_path = tmp_path / "signal_outcomes.csv"
    rows = [
        {
            "signal_id": 1,
            "ticker": "THYAO.IS",
            "score": 26,
            "entry_ts": "2026-08-20T10:00:00+00:00",
            "side": "long",
            "entry_price": 100,
            "stop": 95,
            "target": 110,
            "exit_price": 108,
            "exit_ts": "2026-08-20T11:00:00+00:00",
            "outcome": "TARGET_HIT",
            "holding_min": 60,
            "mfe_pct": 8,
            "mae_pct": -1,
            "gross_pnl": 80,
            "net_pnl": 70,
        },
    ]
    _write_csv(csv_path, rows)
    md = run(csv_path, tmp_path / "out.md")
    assert "yeterli \u00f6rnek yok" in md.lower() or "uyar" in md.lower()
    assert (tmp_path / "out.md").exists()


def test_score_pnl_correlation(tmp_path):
    csv_path = tmp_path / "signal_outcomes.csv"
    # Create 35 rows where higher score → higher pnl (perfect correlation)
    rows = []
    for i in range(35):
        score = 25 + i * 0.5
        pnl = score * 2  # linear
        rows.append(
            {
                "signal_id": i,
                "ticker": "THYAO.IS",
                "score": score,
                "entry_ts": "2026-08-20T10:00:00+00:00",
                "side": "long",
                "entry_price": 100,
                "stop": 95,
                "target": 110,
                "exit_price": 100 + pnl / 100,
                "exit_ts": "2026-08-20T11:00:00+00:00",
                "outcome": "TARGET_HIT" if pnl > 0 else "STOP_HIT",
                "holding_min": 60,
                "mfe_pct": 5,
                "mae_pct": -1,
                "gross_pnl": pnl,
                "net_pnl": pnl,
            }
        )
    _write_csv(csv_path, rows)
    loaded = load_outcomes(csv_path)
    stats = compute_stats(loaded)
    assert stats["score_pnl_corr"] is not None
    assert stats["score_pnl_corr"] > 0.9
