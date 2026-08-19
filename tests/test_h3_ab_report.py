"""H3 A/B report generator tests (scripts/compare_h3_ab.py).

The decision rule is the deliverable of Adım 5, so it is pinned here: improve or
stay flat -> keep, byte-identical arms -> redundant, degrade -> kill-switch
suggestion (never auto-applied).
"""

from __future__ import annotations

import csv
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.compare_h3_ab import (  # noqa: E402
    aggregate,
    build_report,
    decide,
    read_rows,
)

FIELDS = [
    "ticker",
    "status",
    "windows",
    "oos_mean_return",
    "oos_median_return",
    "oos_max_dd",
    "oos_mean_sharpe",
    "is_mean_return",
    "has_overfitting_warning",
    "buy_threshold",
    "total_oos_trades",
    "counter_trend_multiplier",
    "obv_divergence_cap",
    "gates",
    "rows",
]


def write_arm(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDS})
    return path


def arm_rows(values, trades=None):
    trades = trades or {}
    rows = []
    for ticker, oos in values.items():
        rows.append(
            {
                "ticker": ticker,
                "status": "OK" if oos is not None else "INSUFFICIENT_DATA",
                "windows": 8,
                "oos_mean_return": "" if oos is None else oos,
                "oos_median_return": "" if oos is None else oos,
                "oos_max_dd": "" if oos is None else -4.0,
                "oos_mean_sharpe": "" if oos is None else 0.4,
                "is_mean_return": "" if oos is None else 10.0,
                "has_overfitting_warning": "True",
                "total_oos_trades": trades.get(ticker, 10),
                "gates": "ON",
                "rows": 750,
            }
        )
    return rows


def test_identical_arms_are_reported_as_redundant(tmp_path):
    values = {"AAA.IS": 2.0, "BBB.IS": -1.0, "CCC.IS": None}
    on = write_arm(tmp_path / "on.csv", arm_rows(values))
    off = write_arm(tmp_path / "off.csv", arm_rows(values))

    report, verdict = build_report(
        on_rows=read_rows(on),
        off_rows=read_rows(off),
        on_path=on,
        off_path=off,
        diagnose=None,
        diagnose_path=None,
        period="3y",
        cache_note="test",
    )

    assert verdict == "redundant"
    assert "REDUNDANT" in report
    assert "birebir ayni" in report


def test_improvement_keeps_h3(tmp_path):
    on = write_arm(tmp_path / "on.csv", arm_rows({"AAA.IS": 4.0, "BBB.IS": 2.0}))
    off = write_arm(tmp_path / "off.csv", arm_rows({"AAA.IS": 1.0, "BBB.IS": 0.5}))

    report, verdict = build_report(
        on_rows=read_rows(on),
        off_rows=read_rows(off),
        on_path=on,
        off_path=off,
        diagnose=None,
        diagnose_path=None,
        period="3y",
        cache_note="test",
    )

    assert verdict == "keep"
    assert "H3 KALIR" in report


def test_degradation_suggests_kill_switch_without_applying_it(tmp_path):
    on = write_arm(tmp_path / "on.csv", arm_rows({"AAA.IS": 0.5, "BBB.IS": -2.0}))
    off = write_arm(tmp_path / "off.csv", arm_rows({"AAA.IS": 3.0, "BBB.IS": 1.0}))

    report, verdict = build_report(
        on_rows=read_rows(on),
        off_rows=read_rows(off),
        on_path=on,
        off_path=off,
        diagnose=None,
        diagnose_path=None,
        period="3y",
        cache_note="test",
    )

    assert verdict == "kill_switch"
    assert "KILL-SWITCH ONERISI" in report
    assert "KULLANICI ONAYINA TABIDIR" in report


def test_report_contains_per_ticker_delta_and_sasa_focus(tmp_path):
    on = write_arm(
        tmp_path / "on.csv",
        arm_rows({"SASA.IS": -3.0, "AAA.IS": 2.0}, trades={"SASA.IS": 7, "AAA.IS": 10}),
    )
    off = write_arm(
        tmp_path / "off.csv",
        arm_rows({"SASA.IS": -1.0, "AAA.IS": 2.0}, trades={"SASA.IS": 9, "AAA.IS": 10}),
    )

    report, _ = build_report(
        on_rows=read_rows(on),
        off_rows=read_rows(off),
        on_path=on,
        off_path=off,
        diagnose={
            "logged_rows": 12,
            "capped_rows": 5,
            "tickers": ["SASA.IS"],
            "h4_long_fired": 1,
            "h6_neutralized": 2,
        },
        diagnose_path=tmp_path / "diag.csv",
        period="3y",
        cache_note="test",
    )

    assert "SASA.IS odak" in report
    assert "-2.00" in report  # per-ticker OOS delta
    assert "Gercekten cap'lenen satir (capped=YES): 5" in report


def test_aggregate_ignores_insufficient_data_rows(tmp_path):
    path = write_arm(tmp_path / "on.csv", arm_rows({"AAA.IS": 2.0, "BBB.IS": None}))

    agg = aggregate(read_rows(path), "H3 ON")

    assert agg.tickers_total == 2
    assert agg.tickers_ok == 1
    assert agg.mean_oos == 2.0
    assert agg.positive_count == 1


def test_decide_flat_difference_keeps_h3():
    on = aggregate(
        [
            {
                "ticker": "AAA.IS",
                "status": "OK",
                "oos_mean_return": "1.0",
                "oos_max_dd": "-1.0",
                "total_oos_trades": "5",
                "has_overfitting_warning": "False",
            }
        ],
        "on",
    )
    off = aggregate(
        [
            {
                "ticker": "AAA.IS",
                "status": "OK",
                "oos_mean_return": "1.0",
                "oos_max_dd": "-1.0",
                "total_oos_trades": "6",
                "has_overfitting_warning": "False",
            }
        ],
        "off",
    )

    verdict, sentence = decide(on, off, identical=False)

    assert verdict == "keep"
    assert "H3 KALIR" in sentence
