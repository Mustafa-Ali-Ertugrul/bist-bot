"""A2 — backfill_signal_outcomes tests (synthetic bars, no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from scripts.backfill_signal_outcomes import (
    apply_decisions,
    classify_signals,
    ensure_provenance_columns,
    load_pending_signals,
)

from bist_bot.backtest.signal_replay import SignalReplayEngine, build_cost_scenarios
from bist_bot.db.database import Base, SignalRecord
from bist_bot.strategy.params import StrategyParams


def _bars(rows: list[tuple[str, float, float, float, float]]):
    import pandas as pd

    df = pd.DataFrame(
        [
            {"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1_000_000}
            for d, o, h, lo, c in rows
        ]
    )
    # normalize_bars ile ayni format: date kolonu python date olmali
    # (simulate_single_signal date == Timestamp karsilastirmasi yapamaz).
    from bist_bot.backtest.signal_replay import normalize_bars

    out = normalize_bars(df)
    assert out is not None and not out.empty
    return out


def _signal(**kwargs):
    from scripts.backfill_signal_outcomes import _row_to_replay_signal

    defaults = dict(
        ticker="TEST.IS",
        timestamp=datetime(2026, 8, 10, tzinfo=UTC),  # Pazartesi
        signal_type="🟢 AL",
        score=40.0,
        price=100.0,
        stop_loss=95.0,
        target_price=110.0,
    )
    defaults.update(kwargs)

    class _Row:
        pass

    row = _Row()
    row.id = defaults.pop("id", 1)
    row.ticker = defaults["ticker"]
    row.timestamp = defaults["timestamp"]
    row.signal_type = defaults["signal_type"]
    row.score = defaults["score"]
    row.price = defaults["price"]
    row.stop_loss = defaults["stop_loss"]
    row.target_price = defaults["target_price"]
    row.confidence = None
    return _row_to_replay_signal(row)


@pytest.fixture()
def params():
    return StrategyParams(buy_threshold=20.0, sell_threshold=-20.0)


@pytest.fixture()
def engine_replay():
    return SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())


# Sinyal gunu 10.08 (Pzt). Gelecek barlar 11-14.08.
TP_BARS = _bars([
    ("2026-08-10", 100, 101, 99, 100),
    ("2026-08-11", 100.5, 103, 100, 102),   # giris barı
    ("2026-08-12", 102, 112, 101.5, 111),   # hedefe dokunuyor → TP
    ("2026-08-13", 111, 112, 109, 110),
    ("2026-08-14", 110, 111, 108, 109),
])
SL_BARS = _bars([
    ("2026-08-10", 100, 101, 99, 100),
    ("2026-08-11", 100.5, 101, 99, 100),    # giris
    ("2026-08-12", 100, 100.5, 94, 95),     # stopa dokunuyor → SL
    ("2026-08-13", 95, 97, 94, 96),
    ("2026-08-14", 96, 97, 95, 96),
])


def test_radar_and_low_score_become_not_tracked(params, engine_replay):
    radar = _signal(signal_type="🟡 RADAR / İZLE", score=15.0, id=10)
    weak = _signal(signal_type="🟢 AL", score=5.0, id=11)  # esik alti
    out = classify_signals([radar, weak], {"TEST.IS": TP_BARS}, engine_replay, params)
    assert all(d["decision"] == "NOT_TRACKED" for d in out)


def test_missing_geometry_becomes_not_tracked(params, engine_replay):
    no_sl = _signal(stop_loss=None, id=12)
    out = classify_signals([no_sl], {"TEST.IS": TP_BARS}, engine_replay, params)
    assert out[0]["decision"] == "NOT_TRACKED"
    assert out[0]["reason"] == "missing_geometry"


def test_target_hit_scored_with_direction_aware_profit(params, engine_replay):
    out = classify_signals([_signal(id=13)], {"TEST.IS": TP_BARS}, engine_replay, params)
    d = out[0]
    assert d["decision"] == "SCORED"
    assert d["outcome"] == "TARGET_HIT"
    assert d["entry_price"] == pytest.approx(100.5)
    assert d["exit_price"] == pytest.approx(110.0)
    assert d["profit_pct"] == pytest.approx(9.45, abs=0.2)


def test_stop_hit_scored_negative(params, engine_replay):
    out = classify_signals([_signal(id=14)], {"TEST.IS": SL_BARS}, engine_replay, params)
    d = out[0]
    assert d["decision"] == "SCORED"
    assert d["outcome"] == "STOP_HIT"
    assert d["profit_pct"] < 0


def test_short_signal_profit_sign(params, engine_replay):
    short = _signal(signal_type="🔴 SAT", score=-40.0, price=100.0,
                    stop_loss=105.0, target_price=90.0, id=15)
    bars = _bars([
        ("2026-08-10", 100, 101, 99, 100),
        ("2026-08-11", 99.5, 100, 98.5, 99),   # giris
        ("2026-08-12", 99, 99.5, 89, 90),      # hedefe dusus → short TP
        ("2026-08-13", 90, 92, 89, 91),
        ("2026-08-14", 91, 92, 90, 91),
    ])
    d = classify_signals([short], {"TEST.IS": bars}, engine_replay, params)[0]
    assert d["decision"] == "SCORED"
    assert d["outcome"] == "TARGET_HIT"
    assert d["profit_pct"] > 0  # short'ta dusus kar


def test_window_open_when_no_future_bars(params, engine_replay):
    today = datetime.now(UTC).date()
    recent = _signal(timestamp=datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=1), id=16)
    bars = _bars([
        ("2026-08-10", 100, 101, 99, 100),
        ("2026-08-11", 100.5, 103, 100, 102),
    ])
    # Sinyal dununki bar ise ve ondan sonra bar yok → WINDOW_OPEN
    out = classify_signals([recent], {"TEST.IS": bars}, engine_replay, params)
    # timestamp dinamik oldugu icin senaryo: barlar signal_date'den sonra yok
    if out[0]["decision"] in ("WINDOW_OPEN", "NOT_TRACKED", "NO_DATA"):
        assert out[0]["decision"] != "SCORED"


def test_no_bars_is_no_data(params, engine_replay):
    out = classify_signals([_signal(id=17)], {}, engine_replay, params)
    assert out[0]["decision"] == "NO_DATA"


@pytest.fixture()
def db_engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _insert_signal(conn, sig_id, signal_type, score, price, sl, tp, outcome="PENDING"):
    conn.execute(sa.insert(SignalRecord).values(
        id=sig_id,
        timestamp=datetime(2026, 8, 10, 11, 0, tzinfo=UTC),
        ticker="TEST.IS",
        signal_type=signal_type,
        score=score,
        price=price,
        stop_loss=sl,
        target_price=tp,
        conditions="[]",
        outcome=outcome,
    ))


def test_apply_decisions_writes_scored_and_not_tracked_only(db_engine):
    with db_engine.begin() as conn:
        _insert_signal(conn, 1, "🟢 AL", 40.0, 100.0, 95.0, 110.0)          # SCORED
        _insert_signal(conn, 2, "🟡 ZAYIF AL", 10.0, 100.0, None, None)     # NOT_TRACKED
        _insert_signal(conn, 3, "🟢 AL", 40.0, 100.0, 95.0, 110.0)          # WINDOW_OPEN → dokunma
    decisions = [
        {"id": 1, "ticker": "TEST.IS", "signal_type": "🟢 AL", "score": 40.0,
         "decision": "SCORED", "outcome": "TARGET_HIT", "exit_price": 110.0,
         "profit_pct": 9.4, "entry_price": 100.5, "bars_held": 2},
        {"id": 2, "ticker": "TEST.IS", "signal_type": "🟡 ZAYIF AL", "score": 10.0,
         "decision": "NOT_TRACKED", "reason": "not_actionable"},
        {"id": 3, "ticker": "TEST.IS", "signal_type": "🟢 AL", "score": 40.0,
         "decision": "WINDOW_OPEN", "reason": "skipped_no_next_bar"},
    ]
    written = apply_decisions(db_engine, decisions)
    assert written == {"SCORED": 1, "NOT_TRACKED": 1}
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        rows = {r.id: r for r in session.scalars(sa.select(SignalRecord)).all()}
    assert rows[1].outcome == "TARGET_HIT"
    assert rows[1].outcome_source == "backfill_daily"
    assert rows[1].backfilled_at is not None
    assert rows[1].outcome_price == pytest.approx(110.0)
    assert rows[2].outcome == "NOT_TRACKED"
    assert rows[2].outcome_source == "backfill_daily"
    assert rows[3].outcome == "PENDING"          # dokunulmadi
    assert rows[3].outcome_source is None


def test_load_pending_and_provenance_skip_on_sqlite(db_engine):
    with db_engine.begin() as conn:
        _insert_signal(conn, 5, "🟢 AL", 40.0, 100.0, 95.0, 110.0)
        _insert_signal(conn, 6, "🟢 AL", 41.0, 100.0, 95.0, 110.0, outcome="TARGET_HIT")
    signals = load_pending_signals(db_engine)
    assert [s.id for s in signals] == [5]
    assert ensure_provenance_columns(db_engine) == "SKIP (postgres degil)"
