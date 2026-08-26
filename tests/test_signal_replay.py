"""Test suite for the Faz 2 signal replay engine (src/bist_bot/backtest/signal_replay.py).

Uses fully scripted bar data; no DB or network access except the end-to-end
runner test, which uses a temporary SQLite database + offline CSV bars.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from bist_bot.backtest.signal_replay import (
    ReplaySignal,
    SignalReplayEngine,
    analyze_confidence_buckets,
    analyze_score_buckets,
    build_cost_scenarios,
    build_dataset_episodes,
    build_dataset_first_actionable,
    build_dataset_raw,
    calculate_cell_metrics,
    evaluate_entry_delays,
    evaluate_hysteresis,
    evaluate_indicator_filters,
    generate_decision_report,
)
from bist_bot.strategy.signal_models import Signal, SignalType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_bar_df(dates: list[date], opens: list[float], highs: list[float],
                lows: list[float], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1_000_000] * len(dates),
        }
    )


def flat_bars(start: date, n: int, price: float = 100.0) -> pd.DataFrame:
    dates = [date.fromordinal(start.toordinal() + i) for i in range(n)]
    return make_bar_df(
        dates,
        [price] * n,
        [price] * n,
        [price] * n,
        [price] * n,
    )


def make_signal(
    ticker: str = "AAA.IS",
    *,
    signal_date: date = date(2025, 1, 10),
    signal_type: str = SignalType.BUY.value,
    score: float = 28.0,
    price: float = 100.0,
    stop_loss: float | None = 90.0,
    target_price: float | None = 120.0,
    confidence: str | None = "confidence.medium",
    signal_id: int | str = 1,
) -> ReplaySignal:
    ts = datetime(signal_date.year, signal_date.month, signal_date.day, 9, 30, tzinfo=UTC)
    return ReplaySignal(
        id=signal_id,
        ticker=ticker,
        timestamp=ts,
        signal_type=signal_type,
        score=score,
        price=price,
        stop_loss=stop_loss,
        target_price=target_price,
        confidence=confidence,
    )


def replay_one(
    signal: ReplaySignal,
    bars: pd.DataFrame,
    *,
    cost: str = "zero",
    timeout_bars: int = 5,
    delay: int = 0,
) -> tuple:
    engine = SignalReplayEngine(timeout_bars=timeout_bars, cost_models=build_cost_scenarios())
    return engine.simulate_single_signal(
        signal, bars, cost_model_name=cost, dataset_name="raw", entry_delay_bars=delay
    )


# ---------------------------------------------------------------------------
# Exit semantics
# ---------------------------------------------------------------------------


def test_long_tp_hit() -> None:
    sig = make_signal()
    # Entry bar (2025-01-13) + next bar high touches target 120.
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "high"] = 120.0
    trade, status = replay_one(sig, bars)
    assert status == "ok"
    assert trade is not None
    assert trade.exit_reason == "TP"
    assert trade.exit_price == pytest.approx(120.0)
    assert trade.bars_held == 2
    assert trade.entry_date == "2025-01-13"


def test_long_sl_hit() -> None:
    sig = make_signal()
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "low"] = 90.0
    trade, status = replay_one(sig, bars)
    assert status == "ok"
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(90.0)


def test_same_bar_sl_first_long() -> None:
    sig = make_signal(stop_loss=90.0, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "low"] = 85.0
    bars.loc[1, "high"] = 130.0
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(90.0)


def test_same_bar_sl_first_short() -> None:
    sig = make_signal(
        signal_type=SignalType.SELL.value,
        score=-30.0,
        price=100.0,
        stop_loss=110.0,
        target_price=85.0,
    )
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "low"] = 80.0
    bars.loc[1, "high"] = 115.0
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(110.0)


def test_short_tp_hit() -> None:
    sig = make_signal(
        signal_type=SignalType.SELL.value,
        score=-30.0,
        price=100.0,
        stop_loss=110.0,
        target_price=85.0,
    )
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "low"] = 85.0
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "TP"
    assert trade.exit_price == pytest.approx(85.0)


def test_short_sl_hit() -> None:
    sig = make_signal(
        signal_type=SignalType.SELL.value,
        score=-30.0,
        price=100.0,
        stop_loss=110.0,
        target_price=85.0,
    )
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "high"] = 110.0
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# Gap rules
# ---------------------------------------------------------------------------


def test_in_position_gap_exit_long() -> None:
    sig = make_signal(stop_loss=90.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "open"] = 88.0  # opens below stop -> exit at open
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(88.0)


def test_in_position_gap_through_target_long() -> None:
    sig = make_signal(target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "open"] = 125.0  # opens above target -> exit at open
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "TP"
    assert trade.exit_price == pytest.approx(125.0)


def test_in_position_gap_exit_short() -> None:
    sig = make_signal(
        signal_type=SignalType.SELL.value,
        score=-30.0,
        price=100.0,
        stop_loss=110.0,
        target_price=85.0,
    )
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "open"] = 112.0
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(112.0)


def test_entry_bar_gap_cancels_long() -> None:
    # Entry bar open already beyond stop -> setup cancelled, no trade.
    sig = make_signal(stop_loss=90.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[0, "open"] = 88.0
    trade, status = replay_one(sig, bars)
    assert trade is None
    assert status == "skipped_gap_through_stop"

    # Entry bar open already beyond target -> setup cancelled.
    sig2 = make_signal(target_price=120.0)
    bars2 = flat_bars(date(2025, 1, 13), 5)
    bars2.loc[0, "open"] = 125.0
    trade2, status2 = replay_one(sig2, bars2)
    assert trade2 is None
    assert status2 == "skipped_gap_through_target"


def test_entry_bar_gap_cancels_short() -> None:
    sig = make_signal(
        signal_type=SignalType.SELL.value,
        score=-30.0,
        price=100.0,
        stop_loss=110.0,
        target_price=85.0,
    )
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[0, "open"] = 112.0
    trade, status = replay_one(sig, bars)
    assert trade is None
    assert status == "skipped_gap_through_stop"

    bars2 = flat_bars(date(2025, 1, 13), 5)
    bars2.loc[0, "open"] = 82.0
    trade2, status2 = replay_one(sig, bars2)
    assert trade2 is None
    assert status2 == "skipped_gap_through_target"


# ---------------------------------------------------------------------------
# Timeout / data boundaries
# ---------------------------------------------------------------------------


def test_timeout_five_bars() -> None:
    sig = make_signal()
    bars = flat_bars(date(2025, 1, 13), 10, price=100.0)
    trade, _ = replay_one(sig, bars, timeout_bars=5)
    assert trade is not None
    assert trade.exit_reason == "TIMEOUT"
    assert trade.bars_held == 5
    # Exit at the close of the 5th bar (entry + 4).
    assert trade.exit_date == str(date(2025, 1, 17))
    assert trade.exit_price == pytest.approx(100.0)


def test_timeout_data_ended() -> None:
    sig = make_signal()
    # Only 3 bars available after the signal date -> data ends before timeout.
    bars = flat_bars(date(2025, 1, 13), 3)
    trade, _ = replay_one(sig, bars, timeout_bars=5)
    assert trade is not None
    assert trade.exit_reason == "TIMEOUT"
    assert trade.data_ended is True
    assert trade.bars_held == 3


def test_no_next_bar_skip() -> None:
    # Signal on the last available bar date -> no strictly later bar.
    sig = make_signal(signal_date=date(2025, 1, 15))
    bars = flat_bars(date(2025, 1, 13), 3)  # 13, 14, 15 Jan
    trade, status = replay_one(sig, bars)
    assert trade is None
    assert status == "skipped_no_next_bar"


# ---------------------------------------------------------------------------
# Geometry validation
# ---------------------------------------------------------------------------


def test_missing_geometry_skip() -> None:
    sig = make_signal(stop_loss=None, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    trade, status = replay_one(sig, bars)
    assert trade is None
    assert status == "missing_geometry"

    radar = make_signal(signal_type=SignalType.RADAR.value, score=None,
                        stop_loss=None, target_price=None)
    trade2, status2 = replay_one(radar, bars)
    assert trade2 is None
    assert status2 == "is_radar"


def test_invalid_geometry_skip() -> None:
    sig = make_signal(stop_loss=120.0, target_price=90.0)  # long with inverted levels
    bars = flat_bars(date(2025, 1, 13), 5)
    trade, status = replay_one(sig, bars)
    assert trade is None
    assert status == "invalid_geometry"


# ---------------------------------------------------------------------------
# MFE / MAE / R-multiple / costs
# ---------------------------------------------------------------------------


def test_mfe_mae_long() -> None:
    sig = make_signal(stop_loss=90.0, target_price=150.0)
    bars = flat_bars(date(2025, 1, 13), 3)
    bars.loc[1, "high"] = 110.0
    bars.loc[1, "low"] = 95.0
    trade, _ = replay_one(sig, bars, timeout_bars=3)
    assert trade is not None
    assert trade.mfe_pct == pytest.approx(0.10)
    assert trade.mae_pct == pytest.approx(-0.05)
    assert trade.mfe_pct >= 0.0
    assert trade.mae_pct <= 0.0


def test_mfe_mae_short() -> None:
    sig = make_signal(
        signal_type=SignalType.SELL.value,
        score=-30.0,
        price=100.0,
        stop_loss=110.0,
        target_price=85.0,
    )
    bars = flat_bars(date(2025, 1, 13), 3)
    bars.loc[1, "high"] = 105.0
    bars.loc[1, "low"] = 90.0
    trade, _ = replay_one(sig, bars, timeout_bars=3)
    assert trade is not None
    assert trade.mfe_pct == pytest.approx(0.10)   # (100 - 90) / 100
    assert trade.mae_pct == pytest.approx(-0.05)  # (100 - 105) / 100
    assert trade.mfe_pct >= 0.0
    assert trade.mae_pct <= 0.0


def test_r_multiple_long_tp() -> None:
    sig = make_signal(stop_loss=90.0, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "high"] = 120.0
    trade, _ = replay_one(sig, bars)
    assert trade is not None
    # PnL = +20, risk = 10 -> R = 2.0
    assert trade.r_multiple_gross == pytest.approx(2.0)
    assert trade.rr_setup == pytest.approx(2.0)


def test_cost_scenarios_monotonic() -> None:
    engine = SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())
    sig = make_signal(stop_loss=90.0, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "high"] = 120.0

    nets: dict[str, float] = {}
    for cost in ("zero", "base", "stress"):
        trade, _ = engine.simulate_single_signal(
            sig, bars, cost_model_name=cost, dataset_name="raw"
        )
        assert trade is not None
        nets[cost] = trade.net_pnl_pct

    assert nets["zero"] > nets["base"] > nets["stress"]

    # Losing trade: costs make the loss worse (net more negative).
    sig_sl = make_signal(stop_loss=90.0, target_price=120.0)
    bars_sl = flat_bars(date(2025, 1, 13), 5)
    bars_sl.loc[1, "low"] = 90.0
    nets_sl: dict[str, float] = {}
    for cost in ("zero", "base", "stress"):
        trade, _ = engine.simulate_single_signal(
            sig_sl, bars_sl, cost_model_name=cost, dataset_name="raw"
        )
        assert trade is not None
        nets_sl[cost] = trade.net_pnl_pct
    assert nets_sl["zero"] > nets_sl["base"] > nets_sl["stress"]


def test_zero_cost_net_equals_gross() -> None:
    sig = make_signal(stop_loss=90.0, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 5)
    bars.loc[1, "high"] = 120.0
    trade, _ = replay_one(sig, bars, cost="zero")
    assert trade is not None
    assert trade.net_pnl_pct == pytest.approx(trade.gross_pnl_pct)
    assert trade.r_multiple_net == pytest.approx(trade.r_multiple_gross)


# ---------------------------------------------------------------------------
# Dataset builders
# ---------------------------------------------------------------------------


def test_raw_dedup_same_day() -> None:
    sig1 = make_signal(signal_type=SignalType.WEAK_BUY.value, score=15.0, signal_id=1)
    sig2 = make_signal(signal_type=SignalType.BUY.value, score=28.0, signal_id=2)
    raw = build_dataset_raw([sig1, sig2])
    assert len(raw) == 1


def test_episodes_collapse_same_direction() -> None:
    sig1 = make_signal(signal_type=SignalType.WEAK_BUY.value, score=15.0,
                       signal_date=date(2025, 1, 10), signal_id=1)
    sig2 = make_signal(signal_type=SignalType.BUY.value, score=28.0,
                       signal_date=date(2025, 1, 12), signal_id=2)
    sig3 = make_signal(signal_type=SignalType.WEAK_SELL.value, score=-15.0,
                       signal_date=date(2025, 1, 14), signal_id=3)
    bars = flat_bars(date(2025, 1, 9), 10)
    episodes = build_dataset_episodes([sig1, sig2, sig3], {"AAA.IS": bars})
    assert len(episodes) == 2
    assert episodes[0].id == 1
    assert episodes[1].id == 3


def test_episodes_split_on_gap() -> None:
    sig1 = make_signal(signal_type=SignalType.BUY.value, score=28.0,
                       signal_date=date(2025, 1, 10), signal_id=1)
    sig2 = make_signal(signal_type=SignalType.BUY.value, score=30.0,
                       signal_date=date(2025, 1, 24), signal_id=2)  # 10 bars later
    bars = flat_bars(date(2025, 1, 9), 30)
    episodes = build_dataset_episodes([sig1, sig2], {"AAA.IS": bars}, max_gap_bars=5)
    assert len(episodes) == 2


def test_radar_excluded_from_episodes() -> None:
    radar = make_signal(signal_type=SignalType.RADAR.value, score=None,
                        signal_date=date(2025, 1, 10), stop_loss=None,
                        target_price=None, signal_id=1)
    buy = make_signal(signal_type=SignalType.BUY.value, score=28.0,
                      signal_date=date(2025, 1, 12), signal_id=2)
    episodes = build_dataset_episodes([radar, buy], {})
    assert len(episodes) == 1
    assert episodes[0].id == 2


def test_first_actionable_picks_first_actionable() -> None:
    weak = make_signal(signal_type=SignalType.WEAK_BUY.value, score=15.0,
                       signal_date=date(2025, 1, 10), signal_id=1)
    strong = make_signal(signal_type=SignalType.BUY.value, score=28.0,
                         signal_date=date(2025, 1, 12), signal_id=2)
    bars = flat_bars(date(2025, 1, 9), 10)
    fa = build_dataset_first_actionable([weak, strong], {"AAA.IS": bars})
    assert len(fa) == 1
    assert fa[0].id == 2


def test_first_actionable_none_actionable() -> None:
    weak1 = make_signal(signal_type=SignalType.WEAK_BUY.value, score=15.0,
                        signal_date=date(2025, 1, 10), signal_id=1)
    weak2 = make_signal(signal_type=SignalType.WEAK_BUY.value, score=12.0,
                        signal_date=date(2025, 1, 12), signal_id=2)
    bars = flat_bars(date(2025, 1, 9), 10)
    fa = build_dataset_first_actionable([weak1, weak2], {"AAA.IS": bars})
    assert fa == []


# ---------------------------------------------------------------------------
# Guard & analytics
# ---------------------------------------------------------------------------


def _dummy_trade(signal: ReplaySignal, *, exit_reason: str = "TP") -> object:
    from bist_bot.backtest.signal_replay import ReplayTrade

    return ReplayTrade(
        signal_id=signal.id,
        ticker=signal.ticker,
        direction="long",
        signal_type=signal.signal_type,
        signal_score=signal.score,
        confidence=signal.confidence,
        signal_date=str(signal.signal_date),
        entry_date="2025-01-13",
        exit_date="2025-01-14",
        entry_price=100.0,
        exit_price=120.0,
        planned_stop=90.0,
        planned_target=120.0,
        exit_reason=exit_reason,
        gross_pnl_pct=0.2,
        net_pnl_pct=0.19,
        r_multiple_gross=2.0,
        r_multiple_net=1.9,
        mfe_pct=0.2,
        mae_pct=-0.01,
        mfe_r=2.0,
        mae_r=-0.1,
        bars_held=2,
        data_ended=False,
        cost_model_name="base",
        dataset_name="raw",
        total_cost_bps=40.0,
        rr_setup=2.0,
    )


def test_guard_n10_boundary() -> None:
    sig = make_signal(signal_id=0)
    nine = [_dummy_trade(sig, exit_reason="TP" if i % 2 else "SL") for i in range(9)]
    ten = [*nine, _dummy_trade(sig)]

    m9 = calculate_cell_metrics(nine, n_signals=9)
    m10 = calculate_cell_metrics(ten, n_signals=10)

    assert m9["low_n"] is True
    assert m9["recommendation_allowed"] is False
    assert m10["low_n"] is False
    assert m10["recommendation_allowed"] is True


def test_score_buckets_edges() -> None:
    sigs = [
        make_signal(signal_id=i, score=score)
        for i, score in enumerate([7.9, 8.0, 19.9, 20.0, 24.9, 25.0, 40.0])
    ]
    trades = [_dummy_trade(s) for s in sigs]
    buckets = analyze_score_buckets(trades, sigs)
    assert buckets["long_0-8"]["n_signals"] == 1
    assert buckets["long_8-20"]["n_signals"] == 2
    assert buckets["long_20-25"]["n_signals"] == 2
    assert buckets["long_25+"]["n_signals"] == 2


def test_confidence_buckets_string_keys() -> None:
    sigs = [
        make_signal(signal_id=1, confidence="confidence.low"),
        make_signal(signal_id=2, confidence="confidence.high"),
        make_signal(signal_id=3, confidence=None),
    ]
    trades = [_dummy_trade(s) for s in sigs]
    buckets = analyze_confidence_buckets(trades, sigs)
    assert buckets["confidence.low"]["n_signals"] == 1
    assert buckets["confidence.high"]["n_signals"] == 1
    assert buckets["no_conf"]["n_signals"] == 1


def test_decision_report_requires_guard() -> None:
    sigs = [make_signal(signal_id=i) for i in range(9)]
    trades = [_dummy_trade(s) for s in sigs]
    buckets = analyze_score_buckets(trades, sigs)
    decision = generate_decision_report(buckets, guard_threshold=10)
    assert decision["decision_status"] == "no_threshold_change_evidence_accumulation"
    assert decision["eligible_long_cells"] == []
    assert decision["proposals_ready"] is False


# ---------------------------------------------------------------------------
# Variants: delay, hysteresis, indicator filters
# ---------------------------------------------------------------------------


def test_entry_delay_shifts_entry() -> None:
    sig = make_signal(stop_loss=90.0, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 6)
    bars.loc[1, "high"] = 120.0  # TP would hit on delay-0 entry's 2nd bar
    trade0, _ = replay_one(sig, bars, delay=0)
    trade1, _ = replay_one(sig, bars, delay=1)
    assert trade0 is not None and trade0.exit_reason == "TP"
    assert trade1 is not None and trade1.entry_date == "2025-01-14"


def test_entry_delay_out_of_range_skip() -> None:
    sig = make_signal()
    bars = flat_bars(date(2025, 1, 13), 3)
    trade, status = replay_one(sig, bars, delay=5)
    assert trade is None
    assert status == "skipped_no_entry_bar"


def test_hysteresis_second_confirmation() -> None:
    sig1 = make_signal(signal_type=SignalType.BUY.value, score=28.0,
                       signal_date=date(2025, 1, 10), signal_id=1)
    sig2 = make_signal(signal_type=SignalType.BUY.value, score=30.0,
                       signal_date=date(2025, 1, 12), signal_id=2)
    bars = flat_bars(date(2025, 1, 9), 20)
    engine = SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())
    result = evaluate_hysteresis(
        [sig1, sig2], {"AAA.IS": bars}, engine, cost_model_name="zero"
    )
    assert result["confirmed_episodes"] == 1
    assert result["unconfirmed_episodes"] == 0
    assert result["metrics"]["n_traded"] == 1
    assert result["metrics"]["n_signals"] == 1


def test_indicator_filter_ema_no_lookahead() -> None:
    # Long signal; decision bar close (last bar on/before signal date) is below EMA200.
    sig = make_signal(signal_date=date(2025, 1, 10), stop_loss=90.0, target_price=130.0)
    # 240 bars from 2024-06-01 -> well past the signal date (entry bars available).
    bars = flat_bars(date(2024, 6, 1), 240, price=100.0)
    dec_idx = bars.index[bars["date"] <= date(2025, 1, 10)].max()
    assert dec_idx + 5 < len(bars)  # entry bars available after decision bar
    bars.loc[dec_idx, "close"] = 90.0
    bars.loc[dec_idx, "low"] = 88.0
    bars.loc[dec_idx, "high"] = 100.0

    engine = SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())
    result = evaluate_indicator_filters(
        [sig], {"AAA.IS": bars}, engine, cost_model_name="zero", dataset_name="raw"
    )
    # Baseline replayed at least one trade; EMA filter dropped the long (close < EMA200).
    assert result["baseline"]["n_traded"] >= 1
    assert result["ema200_filter"]["dropped_count"] >= 1


def test_evaluate_entry_delays_shape() -> None:
    sig = make_signal(stop_loss=90.0, target_price=120.0)
    bars = flat_bars(date(2025, 1, 13), 10)
    engine = SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())
    delays = evaluate_entry_delays(
        [sig], {"AAA.IS": bars}, engine, cost_model_name="zero", dataset_name="raw"
    )
    assert set(delays.keys()) == {"delay_+0", "delay_+1", "delay_+2", "delay_+3"}
    assert delays["delay_+0"]["n_traded"] == 1
    assert delays["delay_+3"]["n_traded"] == 1


# ---------------------------------------------------------------------------
# End-to-end runner (temp SQLite + offline CSV bars)
# ---------------------------------------------------------------------------


def test_e2e_runner_sqlite_csv(tmp_path) -> None:
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_signal_replay.py"
    spec = importlib.util.spec_from_file_location("run_signal_replay", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main = module.main

    db_path = tmp_path / "signals.db"
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()

    from bist_bot.db.database import DatabaseManager
    from bist_bot.db.repositories.signals_repository import SignalsRepository

    manager = DatabaseManager(sqlite_path=str(db_path))
    repo = SignalsRepository(manager)
    repo.save_signal(
        Signal(
            ticker="AAA.IS",
            signal_type=SignalType.BUY,
            score=28.0,
            price=100.0,
            stop_loss=90.0,
            target_price=120.0,
            timestamp=datetime(2025, 1, 10, 9, 30, tzinfo=UTC),
            confidence="confidence.medium",
        )
    )

    bars = flat_bars(date(2025, 1, 13), 6)
    bars.loc[1, "high"] = 120.0
    bars.to_csv(bars_dir / "AAA.IS.csv", index=False)

    out = tmp_path / "summary.json"
    rc = main(
        [
            "--db-path", str(db_path),
            "--bars-dir", str(bars_dir),
            "--dataset", "raw",
            "--cost", "zero,base",
            "--out", str(out),
            "--min-n", "10",
        ]
    )
    assert rc == 0
    assert out.exists()
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["meta"]["n_signals_loaded"] == 1
    assert summary["blocks"]["raw__zero"]["n_traded"] == 1
    assert summary["blocks"]["raw__zero"]["overall"]["low_n"] is True
    assert summary["decision"]["decision_status"] == "no_threshold_change_evidence_accumulation"
    trades_csv = out.with_name(out.stem + "_trades.csv")
    assert trades_csv.exists()
    df = pd.read_csv(trades_csv)
    assert len(df) == 2  # raw x (zero + base)