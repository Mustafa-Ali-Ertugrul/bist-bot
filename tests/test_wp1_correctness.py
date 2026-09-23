"""WP1 regression tests: P0 correctness fixes.

Covers:
- facade get_recent_closed_trades (paper cooldown no longer AttributeError)
- update_outcome zero-price guard (no ZeroDivisionError / lost outcomes)
- exit order lifecycle attributes (purpose=EXIT, position_id, broker_order_id)
- _parse_exit_reason (no raw JSON blob in exit_reason column)
- alpha_trend dict input (no DataFrame truth ValueError)
- engine._clean_float (no NaN leaking through ``or``)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from bist_bot.agent.exit_service import ExitService, _parse_exit_reason
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.strategy.alpha_trend import AlphaTrendStrategy
from bist_bot.strategy.engine import _clean_float
from bist_bot.strategy.signal_models import Signal, SignalType


@pytest.fixture
def db(tmp_path):
    return DataAccess(DatabaseManager(sqlite_path=str(tmp_path / "wp1.db")))


class TestFacadeCooldown:
    def test_facade_has_get_recent_closed_trades(self, db: DataAccess) -> None:
        # Test yalniz methodun varligini ve bos sonuc dondugunu dogrular.
        assert db.get_recent_closed_trades("THYAO.IS", days=5) == []

    def test_facade_has_get_dashboard_stats_bundle(self, db: DataAccess) -> None:
        # dashboard.py: recent_limit=40 kwarg'i gecer; proxy imzasi buna uygun olmali.
        bundle = db.get_dashboard_stats_bundle(recent_limit=40)
        assert isinstance(bundle, tuple) and len(bundle) == 3


class TestUpdateOutcomeZeroPrice:
    def test_zero_price_does_not_raise_and_keeps_outcome(self, db: DataAccess) -> None:
        db.save_signal(
            Signal(
                ticker="ZERO.IS",
                signal_type=SignalType.BUY,
                score=40.0,
                price=0.0,
                timestamp=datetime.now(UTC),
            )
        )
        rows = db.get_recent_signals(limit=5)
        signal_id = next(r["id"] for r in rows if r["ticker"] == "ZERO.IS")
        # ZeroDivisionError olmadan outcome yazilmali.
        db.update_outcome(signal_id, "TP", 110.0, source="test")
        row = next(r for r in db.get_recent_signals(limit=5) if r["ticker"] == "ZERO.IS")
        assert row["outcome"] == "TP"


class TestExitOrderLifecycle:
    def _make_broker(self, accepted: bool = True, broker_order_id: str = "B-1") -> Any:
        broker = MagicMock()
        broker.authenticate.return_value = True
        result = MagicMock()
        result.accepted = accepted
        result.broker_order_id = broker_order_id
        result.message = ""
        broker.place_order.return_value = result
        return broker

    def test_exit_order_persists_purpose_and_tracking(self, db: DataAccess) -> None:
        svc = ExitService(broker=self._make_broker(), db=db, settings=MagicMock())
        ok = svc.exit_position(
            position_id=123,
            ticker="THYAO.IS",
            quantity=10.0,
            exit_reason="STOP_HIT",
            current_price=99.0,
        )
        assert ok is True
        with db.manager.engine.connect() as conn:
            rows = (
                conn.execute(
                    __import__("sqlalchemy").text("SELECT * FROM orders WHERE purpose='EXIT'")
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        row = rows[0]
        assert row["position_id"] == 123
        assert row["broker_order_id"] == "B-1"
        assert row["state"] == "SENT"
        meta = json.loads(row["metadata_json"])
        assert meta["exit_reason"] == "STOP_HIT"

    def test_parse_exit_reason(self) -> None:
        assert _parse_exit_reason('{"exit_reason": "STOP_HIT"}') == "STOP_HIT"
        assert _parse_exit_reason({"exit_reason": "TP"}) == "TP"
        assert _parse_exit_reason("{}") == "UNKNOWN"
        assert _parse_exit_reason(None) == "UNKNOWN"
        assert _parse_exit_reason("not-json") == "UNKNOWN"


class TestAlphaTrendDictInput:
    def test_dict_input_does_not_raise_on_trend_frame(self) -> None:
        strategy = AlphaTrendStrategy()
        idx = pd.date_range("2026-01-01", periods=80, freq="D")
        frame = pd.DataFrame(
            {
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1_000_000.0,
            },
            index=idx,
        )
        # ``df or other`` ValueError'u: regression — None donmeli (yeterli
        # benchmark yok) veya analiz ilerlemeli; crash ASLA.
        result = strategy.analyze("TEST.IS", {"trend": frame, "trigger": frame.copy()})
        assert result is None or hasattr(result, "ticker")


class TestCleanFloat:
    def test_nan_and_none_fall_back_to_default(self) -> None:
        assert _clean_float(float("nan")) == 0.0
        assert _clean_float(None) == 0.0
        assert _clean_float("abc", 1.5) == 1.5
        assert _clean_float(5.25) == 5.25
        assert _clean_float(float("inf")) == 0.0
