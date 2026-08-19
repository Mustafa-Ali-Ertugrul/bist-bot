"""Stored-signal replay engine tests (Faz 2).

Scripted bars only — no database and no network access. The scenarios cover the
locked exit contract: TP, SL, same-bar SL-first (long + short), gap exits,
timeout, the 5-bar boundary, no-next-bar / invalid-geometry / insufficient-bar
skips, MFE / MAE direction signs, R-multiple, dataset builders and the three
cost scenarios.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.backtest.signal_replay import (  # noqa: E402
    COST_SCENARIOS,
    DATASET_EPISODES,
    DATASET_FIRST_ACTIONABLE,
    DATASET_HYSTERESIS,
    DATASET_RAW,
    LONG,
    MIN_SAMPLE_SIZE,
    OUTCOME_SL,
    OUTCOME_TIMEOUT,
    OUTCOME_TP,
    SHORT,
    SKIP_INSUFFICIENT_BARS,
    SKIP_INVALID_GEOMETRY,
    SKIP_NO_BARS,
    SKIP_NO_NEXT_BAR,
    ReplayConfig,
    ReplaySignal,
    analyze_run,
    build_dataset,
    build_episodes,
    build_summary,
    csv_bar_provider,
    dict_bar_provider,
    entry_delay_analysis,
    guard_report,
    replay_matrix,
    replay_signal,
    resolve_direction,
    run_replay,
    score_bucket_summary,
    signals_from_rows,
    summarize_trades,
    write_summary_json,
    write_trades_csv,
)
from bist_bot.strategy.signal_models import SignalType  # noqa: E402

SIGNAL_DAY = datetime(2025, 3, 3, 12, 0, tzinfo=UTC)


def make_bars(rows: list[dict[str, float]], start: str = "2025-03-04") -> pd.DataFrame:
    """Build a daily OHLC frame starting the first trading day after the signal."""
    index = pd.bdate_range(start=start, periods=len(rows))
    return pd.DataFrame(rows, index=index)


def bar(open_: float, high: float, low: float, close: float) -> dict[str, float]:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000.0}


def make_signal(
    *,
    ticker: str = "TEST.IS",
    signal_type: SignalType = SignalType.BUY,
    score: float = 30.0,
    price: float = 100.0,
    stop_loss: float = 95.0,
    target_price: float = 110.0,
    timestamp: datetime = SIGNAL_DAY,
    confidence: str = "confidence.medium",
) -> ReplaySignal:
    direction = resolve_direction(price, stop_loss, target_price)
    assert direction is not None
    return ReplaySignal(
        ticker=ticker,
        signal_type=signal_type,
        direction=direction,
        score=score,
        price=price,
        stop_loss=stop_loss,
        target_price=target_price,
        confidence=confidence,
        timestamp=timestamp,
    )


def zero_cost_config(**kwargs) -> ReplayConfig:
    return ReplayConfig(cost_scenario="zero", **kwargs)


# ---------------------------------------------------------------------------
# Entry / exit contract
# ---------------------------------------------------------------------------


def test_entry_uses_first_bar_open_after_signal():
    bars = make_bars([bar(101, 102, 100, 101)] * 5)
    trade, skip = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert skip is None
    assert trade is not None
    assert trade.entry_price == 101.0
    assert trade.entry_date == "2025-03-04"


def test_long_take_profit_exit():
    bars = make_bars(
        [
            bar(100, 104, 99, 103),
            bar(103, 112, 102, 111),
            bar(111, 112, 110, 111),
        ]
        + [bar(111, 112, 110, 111)] * 2
    )
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_TP
    assert trade.exit_price == 110.0
    assert trade.holding_bars == 2
    # entry 100, stop 95 -> risk 5; exit 110 -> +10 => 2R
    assert trade.r_multiple == pytest.approx(2.0)


def test_long_stop_loss_exit():
    bars = make_bars(
        [
            bar(100, 101, 99, 100),
            bar(100, 100, 94, 95),
        ]
        + [bar(95, 96, 94, 95)] * 3
    )
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_SL
    assert trade.exit_price == 95.0
    assert trade.r_multiple == pytest.approx(-1.0)


def test_same_bar_hits_both_levels_long_takes_stop_first():
    bars = make_bars([bar(100, 115, 90, 112)] + [bar(112, 113, 111, 112)] * 4)
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_SL
    assert trade.exit_price == 95.0
    assert trade.exit_detail == "intrabar"


def test_same_bar_hits_both_levels_short_takes_stop_first():
    signal = make_signal(
        signal_type=SignalType.SELL, score=-30.0, price=100.0, stop_loss=105.0, target_price=92.0
    )
    bars = make_bars([bar(100, 115, 90, 95)] + [bar(95, 96, 94, 95)] * 4)
    trade, _ = replay_signal(signal, bars, config=zero_cost_config())

    assert trade.direction == SHORT
    assert trade.outcome == OUTCOME_SL
    assert trade.exit_price == 105.0
    assert trade.r_multiple == pytest.approx(-1.0)


def test_short_take_profit_r_multiple():
    signal = make_signal(
        signal_type=SignalType.SELL, score=-30.0, price=100.0, stop_loss=105.0, target_price=92.0
    )
    bars = make_bars(
        [
            bar(100, 101, 98, 99),
            bar(99, 100, 91, 92),
        ]
        + [bar(92, 93, 91, 92)] * 3
    )
    trade, _ = replay_signal(signal, bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_TP
    assert trade.exit_price == 92.0
    # entry 100, stop 105 -> risk 5; short profit 8 => 1.6R
    assert trade.r_multiple == pytest.approx(1.6)


def test_gap_down_long_exits_at_open_not_at_stop():
    bars = make_bars(
        [
            bar(100, 102, 99, 101),
            bar(90, 91, 88, 89),
        ]
        + [bar(89, 90, 88, 89)] * 3
    )
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_SL
    assert trade.exit_detail == "gap_open"
    assert trade.exit_price == 90.0
    assert trade.r_multiple == pytest.approx(-2.0)


def test_gap_up_long_exits_at_open_above_target():
    bars = make_bars(
        [
            bar(100, 102, 99, 101),
            bar(118, 120, 117, 119),
        ]
        + [bar(119, 120, 118, 119)] * 3
    )
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_TP
    assert trade.exit_detail == "gap_open"
    assert trade.exit_price == 118.0


def test_entry_bar_open_is_not_treated_as_a_gap():
    """The entry fill is the open, so the open itself can never gap the levels."""
    bars = make_bars([bar(100, 101, 99, 100)] + [bar(100, 101, 99, 100)] * 4)
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_TIMEOUT
    assert trade.holding_bars == 5


def test_timeout_exits_at_last_bar_close_after_five_bars():
    bars = make_bars(
        [bar(100, 101, 99, 100)] * 4 + [bar(100, 102, 99, 102)] + [bar(102, 103, 101, 102)]
    )
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade.outcome == OUTCOME_TIMEOUT
    assert trade.holding_bars == 5
    assert trade.exit_price == 102.0
    assert trade.exit_date == "2025-03-10"


def test_timeout_bars_is_configurable():
    bars = make_bars([bar(100, 101, 99, 100)] * 6)
    trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config(timeout_bars=3))

    assert trade.holding_bars == 3
    assert trade.outcome == OUTCOME_TIMEOUT


# ---------------------------------------------------------------------------
# Skips
# ---------------------------------------------------------------------------


def test_signal_without_next_bar_is_skipped():
    bars = make_bars([bar(100, 101, 99, 100)], start="2025-02-03")
    trade, skip = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade is None
    assert skip.reason == SKIP_NO_NEXT_BAR


def test_missing_bars_are_skipped():
    trade, skip = replay_signal(make_signal(), None, config=zero_cost_config())

    assert trade is None
    assert skip.reason == SKIP_NO_BARS


def test_open_position_with_truncated_history_is_skipped_as_insufficient_bars():
    bars = make_bars([bar(100, 101, 99, 100)] * 3)
    trade, skip = replay_signal(make_signal(), bars, config=zero_cost_config())

    assert trade is None
    assert skip.reason == SKIP_INSUFFICIENT_BARS


def test_invalid_geometry_signal_is_rejected_at_load_time():
    rows = [
        {
            "ticker": "BAD.IS",
            "signal_type": SignalType.BUY.value,
            "score": 30.0,
            "price": 100.0,
            "stop_loss": 105.0,  # stop above price on a long plan
            "target_price": 110.0,
            "confidence": "confidence.low",
            "timestamp": SIGNAL_DAY.isoformat(),
        },
        {
            "ticker": "FLAT.IS",
            "signal_type": SignalType.SELL.value,
            "score": -30.0,
            "price": 100.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
            "confidence": "confidence.low",
            "timestamp": SIGNAL_DAY.isoformat(),
        },
    ]
    signals, skipped = signals_from_rows(rows)

    assert signals == []
    assert {item.reason for item in skipped} == {SKIP_INVALID_GEOMETRY}


def test_geometry_resolution_directions():
    assert resolve_direction(100, 95, 110) == LONG
    assert resolve_direction(100, 105, 92) == SHORT
    assert resolve_direction(100, 95, 90) is None
    assert resolve_direction(0, 95, 110) is None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_mfe_and_mae_are_direction_aware_magnitudes():
    bars = make_bars([bar(100, 107, 96, 101)] * 5)
    long_trade, _ = replay_signal(make_signal(), bars, config=zero_cost_config())

    # long: favourable = high - entry = 7 -> 1.4R, adverse = entry - low = 4 -> 0.8R
    assert long_trade.mfe_r == pytest.approx(1.4)
    assert long_trade.mae_r == pytest.approx(0.8)

    short_signal = make_signal(
        signal_type=SignalType.SELL, score=-30.0, price=100.0, stop_loss=108.0, target_price=90.0
    )
    short_trade, _ = replay_signal(short_signal, bars, config=zero_cost_config())

    # short: favourable = entry - low = 4 -> 0.5R, adverse = high - entry = 7 -> 0.875R
    assert short_trade.mfe_r == pytest.approx(0.5)
    assert short_trade.mae_r == pytest.approx(0.875)
    assert short_trade.mfe_r >= 0 and short_trade.mae_r >= 0


def test_cost_scenarios_order_net_results():
    bars = make_bars(
        [bar(100, 104, 99, 103), bar(103, 112, 102, 111)] + [bar(111, 112, 110, 111)] * 3
    )
    signal = make_signal()
    results = {}
    for scenario in ("zero", "base", "stress"):
        trade, _ = replay_signal(
            signal,
            bars,
            config=ReplayConfig(cost_scenario=scenario),
            cost_model=COST_SCENARIOS[scenario],
        )
        results[scenario] = trade

    assert results["zero"].fees_tl == 0.0
    assert results["zero"].slippage_tl == 0.0
    assert results["zero"].net_pnl_tl == pytest.approx(results["zero"].gross_pnl_tl)
    assert results["base"].fees_tl > 0
    assert results["stress"].fees_tl > results["base"].fees_tl
    assert results["stress"].slippage_tl > results["base"].slippage_tl
    # Gross is cost-independent; net degrades monotonically with the scenario.
    assert results["zero"].gross_pnl_tl == pytest.approx(results["stress"].gross_pnl_tl)
    assert results["zero"].net_r_multiple > results["base"].net_r_multiple
    assert results["base"].net_r_multiple > results["stress"].net_r_multiple


def test_context_columns_are_taken_from_the_decision_bar():
    rows = [
        bar(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1) for i in range(40)
    ]
    frame = pd.DataFrame(rows, index=pd.bdate_range("2025-01-02", periods=40))
    provider = dict_bar_provider({"TEST.IS": frame})
    signal = make_signal(timestamp=datetime(2025, 2, 10, 12, 0, tzinfo=UTC))

    trade, skip = replay_signal(signal, provider("TEST.IS"), config=zero_cost_config())

    assert skip is None
    assert trade.above_ema200 is True  # rising series stays above its EMA200
    assert trade.rsi_at_signal is not None


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


def _episode_fixture() -> list[ReplaySignal]:
    return [
        make_signal(
            ticker="AAA.IS",
            signal_type=SignalType.WEAK_BUY,
            score=12.0,
            timestamp=datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
        ),
        make_signal(
            ticker="AAA.IS",
            signal_type=SignalType.WEAK_BUY,
            score=27.0,
            timestamp=datetime(2025, 3, 4, 10, 0, tzinfo=UTC),
        ),
        make_signal(
            ticker="AAA.IS",
            signal_type=SignalType.BUY,
            score=31.0,
            timestamp=datetime(2025, 3, 5, 10, 0, tzinfo=UTC),
        ),
        make_signal(
            ticker="BBB.IS",
            signal_type=SignalType.WEAK_BUY,
            score=9.0,
            timestamp=datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
        ),
    ]


def test_build_episodes_collapses_consecutive_same_type_signals():
    episodes = build_episodes(_episode_fixture())

    assert [len(episode) for episode in episodes] == [2, 1, 1]
    assert episodes[0][0].ticker == "AAA.IS"
    assert episodes[0][0].signal_type is SignalType.WEAK_BUY


def test_episode_dataset_keeps_first_signal_of_each_episode():
    selected = build_dataset(_episode_fixture(), DATASET_EPISODES, buy_threshold=25.0)

    assert len(selected) == 3
    assert [item.score for item in selected] == [12.0, 31.0, 9.0]


def test_first_actionable_dataset_picks_the_first_signal_above_threshold():
    selected = build_dataset(_episode_fixture(), DATASET_FIRST_ACTIONABLE, buy_threshold=25.0)

    # AAA weak-buy episode: 12 is below, 27 is the first actionable one.
    # AAA buy episode qualifies at 31. BBB (9) never becomes actionable.
    assert [(item.ticker, item.score) for item in selected] == [("AAA.IS", 27.0), ("AAA.IS", 31.0)]


def test_first_actionable_is_symmetric_for_shorts():
    shorts = [
        make_signal(
            ticker="CCC.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-12.0,
            price=100.0,
            stop_loss=105.0,
            target_price=92.0,
            timestamp=datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
        ),
        make_signal(
            ticker="CCC.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-28.0,
            price=100.0,
            stop_loss=105.0,
            target_price=92.0,
            timestamp=datetime(2025, 3, 4, 10, 0, tzinfo=UTC),
        ),
    ]
    selected = build_dataset(shorts, DATASET_FIRST_ACTIONABLE, buy_threshold=25.0)

    assert [item.score for item in selected] == [-28.0]


def test_radar_signals_are_never_actionable():
    radar = make_signal(signal_type=SignalType.RADAR, score=40.0)

    assert radar.is_actionable(25.0) is False
    assert build_dataset([radar], DATASET_FIRST_ACTIONABLE, buy_threshold=25.0) == []


def test_hysteresis_dataset_uses_the_second_confirmation():
    selected = build_dataset(_episode_fixture(), DATASET_HYSTERESIS, buy_threshold=25.0)

    assert [item.score for item in selected] == [27.0]


def test_raw_dataset_keeps_every_signal_and_stamps_episode_metadata():
    selected = build_dataset(_episode_fixture(), DATASET_RAW, buy_threshold=25.0)

    assert len(selected) == 4
    assert selected[0].episode_size == 2
    assert selected[1].episode_position == 1


# ---------------------------------------------------------------------------
# Aggregation + guard
# ---------------------------------------------------------------------------


def _run_with_n_trades(count: int) -> list[ReplaySignal]:
    signals = []
    for index in range(count):
        signals.append(
            make_signal(
                ticker=f"T{index}.IS",
                score=30.0,
                timestamp=datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
            )
        )
    return signals


def _winning_frames(tickers: list[str]) -> dict[str, pd.DataFrame]:
    frame = make_bars(
        [bar(100, 104, 99, 103), bar(103, 112, 102, 111)] + [bar(111, 112, 110, 111)] * 3
    )
    return {ticker: frame for ticker in tickers}


def test_summary_flags_low_n_below_the_guard():
    signals = _run_with_n_trades(4)
    provider = dict_bar_provider(_winning_frames([s.ticker for s in signals]))
    run = run_replay(signals, provider, config=zero_cost_config())

    summary = summarize_trades(run.trades)

    assert summary["n"] == 4
    assert summary["low_n"] is True
    assert summary["recommendation_allowed"] is False
    assert summary["min_sample_size"] == MIN_SAMPLE_SIZE
    assert summary["win_rate_pct"] == 100.0
    assert summary["avg_r"] == pytest.approx(2.0)


def test_summary_clears_the_guard_at_ten_trades():
    signals = _run_with_n_trades(10)
    provider = dict_bar_provider(_winning_frames([s.ticker for s in signals]))
    run = run_replay(signals, provider, config=zero_cost_config())

    summary = summarize_trades(run.trades)

    assert summary["n"] == 10
    assert summary["low_n"] is False
    assert summary["recommendation_allowed"] is True


def test_guard_report_never_auto_recommends_a_threshold_change():
    signals = _run_with_n_trades(12)
    provider = dict_bar_provider(_winning_frames([s.ticker for s in signals]))
    run = run_replay(signals, provider, config=zero_cost_config())

    buckets = score_bucket_summary(run.trades)
    report = guard_report(buckets)

    assert "long:25+" in buckets
    assert report["eligible_buckets"] == ["long:25+"]
    assert report["threshold_change_recommended"] is False


def test_analyze_run_reports_filters_and_skips():
    signals = _run_with_n_trades(3)
    frames = _winning_frames([s.ticker for s in signals])
    frames["MISSING.IS"] = pd.DataFrame()
    signals.append(make_signal(ticker="MISSING.IS"))
    run = run_replay(signals, dict_bar_provider(frames), config=zero_cost_config())

    analysis = analyze_run(run)

    assert analysis["overall"]["n"] == 3
    assert analysis["skipped"]["total"] == 1
    assert analysis["skipped"]["by_reason"][SKIP_NO_BARS] == 1
    assert analysis["ema200_filter"]["delta"]["n_delta"] <= 0
    assert "rule" in analysis["rsi_extreme_veto"]
    assert analysis["guard"]["threshold_change_recommended"] is False


def test_entry_delay_analysis_covers_one_two_and_three_bars():
    signals = _run_with_n_trades(2)
    frame = make_bars([bar(100, 101, 99, 100)] * 10)
    provider = dict_bar_provider({s.ticker: frame for s in signals})

    analysis = entry_delay_analysis(signals, provider, config=zero_cost_config())

    assert set(analysis["variants"]) == {"delay_1", "delay_2", "delay_3"}
    assert analysis["variants"]["delay_1"]["summary"]["n"] == 2
    assert "delta_vs_delay_1" in analysis["variants"]["delay_2"]


def test_replay_matrix_and_summary_payload(tmp_path):
    signals = _run_with_n_trades(3)
    provider = dict_bar_provider(_winning_frames([s.ticker for s in signals]))

    runs, dataset_signals = replay_matrix(
        signals,
        provider,
        datasets=(DATASET_RAW, DATASET_EPISODES),
        cost_scenarios=("zero", "base"),
        config=ReplayConfig(),
        buy_threshold=25.0,
    )
    payload = build_summary(
        signals=signals,
        rejected=[],
        runs=runs,
        dataset_signals=dataset_signals,
        config=ReplayConfig(),
        buy_threshold=25.0,
    )

    assert set(payload["datasets"]) == {DATASET_RAW, DATASET_EPISODES}
    assert set(payload["datasets"][DATASET_RAW]["costs"]) == {"zero", "base"}
    assert payload["decision"]["threshold_change_recommended"] is False
    assert payload["signal_inventory"]["valid_signals"] == 3
    assert payload["config"]["min_sample_size"] == MIN_SAMPLE_SIZE

    summary_path = write_summary_json(payload, tmp_path / "summary.json")
    trades_path = write_trades_csv(runs[DATASET_RAW]["base"].trades, tmp_path / "trades.csv")

    assert summary_path.exists()
    assert trades_path.exists()
    csv_text = trades_path.read_text(encoding="utf-8")
    assert "r_multiple" in csv_text.splitlines()[0]
    assert len(csv_text.strip().splitlines()) == 4  # header + 3 trades


def test_signals_from_rows_normalizes_and_sorts():
    rows = [
        {
            "ticker": "ZZZ.IS",
            "signal_type": SignalType.SELL.value,
            "score": -30.0,
            "price": 100.0,
            "stop_loss": 105.0,
            "target_price": 92.0,
            "confidence": "confidence.high",
            "timestamp": "2025-03-05T10:00:00+00:00",
        },
        {
            "ticker": "AAA.IS",
            "signal_type": SignalType.BUY.value,
            "score": 30.0,
            "price": 100.0,
            "stop_loss": 95.0,
            "target_price": 110.0,
            "confidence": "confidence.medium",
            "timestamp": "2025-03-04T10:00:00Z",
        },
    ]
    signals, skipped = signals_from_rows(rows)

    assert skipped == []
    assert [item.ticker for item in signals] == ["AAA.IS", "ZZZ.IS"]
    assert signals[0].direction == LONG
    assert signals[1].direction == SHORT
    assert signals[0].planned_rr == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Offline CSV bars + end-to-end runner
# ---------------------------------------------------------------------------


def test_csv_bar_provider_reads_offline_bars(tmp_path):
    frame = _winning_frames(["THYAO.IS"])["THYAO.IS"]
    frame.to_csv(tmp_path / "THYAO.IS.csv")

    provider = csv_bar_provider(tmp_path)
    bars = provider("THYAO.IS")

    assert bars is not None
    assert list(bars.columns[:4]) == ["open", "high", "low", "close"]
    assert provider("UNKNOWN.IS") is None

    trade, skip = replay_signal(make_signal(ticker="THYAO.IS"), bars, config=zero_cost_config())
    assert skip is None
    assert trade.outcome == OUTCOME_TP


def test_runner_end_to_end_with_stored_signals(tmp_path):
    """Full 2B path: repository read -> replay -> CSV + JSON artifacts."""
    import scripts.run_signal_replay as runner

    from bist_bot.db.database import DatabaseManager
    from bist_bot.db.repositories.signals_repository import SignalsRepository
    from bist_bot.strategy.signal_models import Signal

    db_path = tmp_path / "replay_test.db"
    manager = DatabaseManager(sqlite_path=str(db_path))
    repo = SignalsRepository(manager=manager)
    try:
        for index in range(3):
            repo.save_signal(
                Signal(
                    ticker="THYAO.IS",
                    signal_type=SignalType.BUY,
                    score=30.0 + index,
                    price=100.0,
                    stop_loss=95.0,
                    target_price=110.0,
                    timestamp=datetime(2025, 3, 3 + index, 10, 0, tzinfo=UTC),
                    confidence="confidence.medium",
                )
            )

        bars_dir = tmp_path / "bars"
        bars_dir.mkdir()
        frame = make_bars(
            [bar(100, 104, 99, 103), bar(103, 112, 102, 111)] + [bar(111, 112, 110, 111)] * 6,
            start="2025-03-04",
        )
        frame.to_csv(bars_dir / "THYAO.IS.csv")

        summary_path = tmp_path / "summary.json"
        exit_code = runner.main(
            [
                "--dataset",
                "raw",
                "--cost",
                "base",
                "--bars-dir",
                str(bars_dir),
                "--db-path",
                str(db_path),
                "--out",
                str(summary_path),
            ]
        )
    finally:
        manager.session_factory.remove()
        manager.engine.dispose()

    assert exit_code == 0
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["signal_inventory"]["valid_signals"] == 3
    overall = payload["datasets"]["raw"]["costs"]["base"]["overall"]
    assert overall["n"] >= 1
    assert overall["low_n"] is True  # 3 trades never clears the N >= 10 guard
    assert payload["decision"]["threshold_change_recommended"] is False
    assert "entry_delay" in payload["variants"]
    assert "hysteresis" in payload["variants"]

    trades_csv = summary_path.with_name("summary_trades.csv")
    assert trades_csv.exists()
    assert "r_multiple" in trades_csv.read_text(encoding="utf-8").splitlines()[0]


def test_runner_without_signals_writes_guarded_empty_summary(tmp_path, monkeypatch):
    import scripts.run_signal_replay as runner

    monkeypatch.setattr(runner, "load_stored_signals", lambda **kwargs: ([], []))
    summary_path = tmp_path / "empty.json"

    exit_code = runner.main(["--out", str(summary_path)])

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "no_stored_signals"
    assert payload["datasets"] == {}
    assert payload["decision"]["threshold_change_recommended"] is False
    assert (tmp_path / "empty_trades.csv").exists()
