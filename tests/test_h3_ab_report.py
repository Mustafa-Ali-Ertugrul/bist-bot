"""H3 A/B rapor üreticisinin karar kuralı ve aggregate testleri.

``scripts/compare_h3_ab.py`` bir paket modülü olmadığı için importlib ile
yüklenir; testler saf-fonksiyon karar kuralını ve aggregate metriklerini
kilitler.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "compare_h3_ab", _REPO_ROOT / "scripts" / "compare_h3_ab.py"
)
assert _spec is not None and _spec.loader is not None
compare_h3_ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_h3_ab)


def _row(
    ticker: str,
    oos: float,
    trades: int = 5,
    *,
    is_ret: float = 5.0,
    overfit: object = "False",
    status: str = "OK",
) -> dict[str, str]:
    return {
        "ticker": ticker,
        "status": status,
        "oos_mean_return": str(oos),
        "oos_median_return": str(oos),
        "oos_max_dd": "-5.0",
        "oos_mean_sharpe": "0.0",
        "is_mean_return": str(is_ret),
        "has_overfitting_warning": str(overfit) if not isinstance(overfit, bool) else overfit,
        "total_oos_trades": str(trades),
        "windows": "7",
    }


class TestDecisionRule:
    def test_identical_arms_verdict_redundant(self):
        arm = [_row("AKBNK.IS", 2.0), _row("GARAN.IS", 4.0)]
        on_agg = compare_h3_ab.aggregate(arm)
        off_agg = compare_h3_ab.aggregate(arm)
        deltas, on_only, off_only = compare_h3_ab.per_ticker_deltas(arm, arm)
        assert compare_h3_ab.arms_identical(deltas, on_only, off_only) is True
        key, sentence = compare_h3_ab.decide(on_agg, off_agg, all_identical=True)
        assert key == "redundant"
        assert "H3 redundant" in sentence

    def test_on_better_verdict_keep(self):
        on = [_row("AKBNK.IS", 3.0), _row("GARAN.IS", 5.0)]
        off = [_row("AKBNK.IS", 2.0), _row("GARAN.IS", 4.0)]
        key, sentence = compare_h3_ab.decide(
            compare_h3_ab.aggregate(on),
            compare_h3_ab.aggregate(off),
            all_identical=False,
        )
        assert key == "keep"
        assert "H3 kalır" in sentence

    def test_on_worse_verdict_kill_switch(self):
        on = [_row("AKBNK.IS", 1.0), _row("GARAN.IS", 3.0)]
        off = [_row("AKBNK.IS", 2.0), _row("GARAN.IS", 4.0)]
        key, sentence = compare_h3_ab.decide(
            compare_h3_ab.aggregate(on),
            compare_h3_ab.aggregate(off),
            all_identical=False,
        )
        assert key == "kill_switch"
        assert "kill-switch önerilir" in sentence
        assert "kullanıcı onayı" in sentence

    def test_marginal_delta_verdict_keep_with_note(self):
        on = [_row("AKBNK.IS", 2.05), _row("GARAN.IS", 4.05)]
        off = [_row("AKBNK.IS", 2.0), _row("GARAN.IS", 4.0)]
        key, sentence = compare_h3_ab.decide(
            compare_h3_ab.aggregate(on),
            compare_h3_ab.aggregate(off),
            all_identical=False,
        )
        assert key == "keep"
        assert "marjinal" in sentence

    def test_empty_arm_verdict_no_data(self):
        key, _ = compare_h3_ab.decide(
            compare_h3_ab.aggregate([]),
            compare_h3_ab.aggregate([_row("AKBNK.IS", 1.0)]),
            all_identical=False,
        )
        assert key == "no_data"


class TestAggregate:
    def test_non_ok_rows_excluded(self):
        rows = [
            _row("AKBNK.IS", 2.0),
            _row("AEFES.IS", 9.9, status="INSUFFICIENT_DATA"),
        ]
        agg = compare_h3_ab.aggregate(rows)
        assert agg["n"] == 1
        assert agg["mean_oos"] == pytest.approx(2.0)

    def test_is_plus_oos_minus_share(self):
        rows = [
            _row("AKBNK.IS", -1.0, is_ret=6.0),  # IS+ / OOS- → yapısal overfit
            _row("GARAN.IS", 3.0, is_ret=6.0),  # her ikisi pozitif
        ]
        agg = compare_h3_ab.aggregate(rows)
        assert agg["is_plus_oos_minus_share"] == pytest.approx(50.0)

    def test_overfit_flag_share_accepts_bool_and_string(self):
        rows = [
            _row("AKBNK.IS", 1.0, overfit=True),
            _row("GARAN.IS", 2.0, overfit="False"),
        ]
        agg = compare_h3_ab.aggregate(rows)
        assert agg["overfit_flag_share"] == pytest.approx(50.0)

    def test_arms_with_different_universe_not_identical(self):
        on = [_row("AKBNK.IS", 2.0), _row("SASA.IS", 1.0)]
        off = [_row("AKBNK.IS", 2.0)]
        deltas, on_only, off_only = compare_h3_ab.per_ticker_deltas(on, off)
        assert compare_h3_ab.arms_identical(deltas, on_only, off_only) is False
        assert on_only == ["SASA.IS"]
        assert off_only == []


class TestDiagnoseSummary:
    def test_summarize_handles_missing_file(self, tmp_path: Path):
        assert compare_h3_ab.summarize_diagnose(tmp_path / "nope.csv") is None

    def test_summarize_counts_candidates_and_capped(self, tmp_path: Path):
        csv_path = tmp_path / "chase.csv"
        csv_path.write_text(
            "ticker,window_idx,capped,high_score,raw_score,capped_score\n"
            "AKBNK.IS,1,True,YES,45.0,10.0\n"
            "AKBNK.IS,2,False,no,22.0,22.0\n"
            "SASA.IS,1,True,YES,60.0,20.0\n",
            encoding="utf-8",
        )
        summary = compare_h3_ab.summarize_diagnose(csv_path)
        assert summary is not None
        assert summary["candidates"] == 3
        assert summary["capped"] == 2
        assert summary["high_score_rows"] == 2
        assert summary["per_ticker_capped"] == {"AKBNK.IS": 1, "SASA.IS": 1}
        assert summary["mean_cap_gap"] == pytest.approx((35.0 + 40.0) / 2)
        assert summary["max_raw"] == pytest.approx(60.0)
        assert summary["rows_raw_ge_buy_threshold"] == 2
