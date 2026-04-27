"""Tests for overview page data handling and session fallback."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


def _build_stats_response(stats_dict, latest_scan=None):
    """Simulate /api/stats JSON response."""
    payload = {"status": "ok", "stats": dict(stats_dict)}
    if latest_scan is not None:
        payload["stats"]["latest_scan"] = latest_scan
        payload["latest_scan"] = latest_scan
    return payload


def _build_signals_response(signals_list):
    """Simulate /api/signals/history JSON response."""
    return {"status": "ok", "signals": signals_list}


def test_latest_scan_read_from_stats_inner():
    """UI reads latest_scan from stats['latest_scan'] (primary location)."""
    response = _build_stats_response(
        {"total_signals": 5, "win_rate": 60.0},
        latest_scan={"total_scanned": 20, "signals_generated": 3, "actionable": 3},
    )
    stats = response["stats"]
    latest_scan = stats.get("latest_scan") or response.get("latest_scan")
    assert latest_scan is not None
    assert latest_scan["total_scanned"] == 20
    assert latest_scan["actionable"] == 3


def test_latest_scan_read_from_top_level_fallback():
    """UI reads latest_scan from top-level when stats dict lacks it."""
    response = {
        "status": "ok",
        "stats": {"total_signals": 5},
        "latest_scan": {"total_scanned": 15, "signals_generated": 0},
    }
    stats = response["stats"]
    latest_scan = stats.get("latest_scan") or response.get("latest_scan")
    assert latest_scan is not None
    assert latest_scan["total_scanned"] == 15


def test_actionable_falls_back_to_signals_generated():
    """actionable count uses signals_generated when actionable key is absent."""
    latest_scan = {"total_scanned": 20, "signals_generated": 5}
    actionable = latest_scan.get("actionable", latest_scan.get("signals_generated", 0))
    assert actionable == 5


def test_actionable_uses_actionable_key_when_present():
    """actionable count prefers explicit actionable key."""
    latest_scan = {"total_scanned": 20, "signals_generated": 5, "actionable": 3}
    actionable = latest_scan.get("actionable", latest_scan.get("signals_generated", 0))
    assert actionable == 3


def test_session_signals_fallback_when_api_history_empty():
    """When /api/signals/history returns empty but session has signals, use session data."""
    session_signals = [
        Signal(ticker="ASELS.IS", signal_type=SignalType.HOLD, score=3, price=150.0),
        Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0),
    ]
    api_history = []

    recent_signals = api_history
    if not recent_signals and session_signals:
        recent_signals = [
            {
                "ticker": s.ticker,
                "signal_type": s.signal_type.value,
                "score": s.score,
                "price": s.price,
                "position_size": s.position_size,
                "outcome": "PENDING",
                "timestamp": s.timestamp.isoformat() if s.timestamp else "",
            }
            for s in session_signals[:10]
        ]

    assert len(recent_signals) == 2
    assert recent_signals[0]["ticker"] == "ASELS.IS"
    assert recent_signals[0]["signal_type"] == SignalType.HOLD.value
    assert recent_signals[1]["ticker"] == "THYAO.IS"
    assert recent_signals[1]["signal_type"] == SignalType.BUY.value


def test_hold_signals_in_session_fallback():
    """HOLD/BEKLE signals are included in session fallback for recent flow."""
    session_signals = [
        Signal(ticker="ASELS.IS", signal_type=SignalType.HOLD, score=3, price=150.0),
        Signal(ticker="GARAN.IS", signal_type=SignalType.HOLD, score=-1, price=80.0),
    ]
    api_history = []

    recent_signals = api_history
    if not recent_signals and session_signals:
        recent_signals = [
            {
                "ticker": s.ticker,
                "signal_type": s.signal_type.value,
                "score": s.score,
                "price": s.price,
                "position_size": s.position_size,
                "outcome": "PENDING",
                "timestamp": s.timestamp.isoformat() if s.timestamp else "",
            }
            for s in session_signals[:10]
        ]

    assert len(recent_signals) == 2
    assert all(r["signal_type"] == SignalType.HOLD.value for r in recent_signals)


def test_no_fallback_when_both_api_and_session_empty():
    """When both API history and session signals are empty, recent_signals stays empty."""
    session_signals = []
    api_history = []

    recent_signals = api_history
    if not recent_signals and session_signals:
        recent_signals = [
            {
                "ticker": s.ticker,
                "signal_type": s.signal_type.value,
                "score": s.score,
                "price": s.price,
                "position_size": s.position_size,
                "outcome": "PENDING",
                "timestamp": s.timestamp.isoformat() if s.timestamp else "",
            }
            for s in session_signals[:10]
        ]

    assert recent_signals == []


def test_latest_scan_with_none_value():
    """UI handles latest_scan being None gracefully."""
    response = {"status": "ok", "stats": {"total_signals": 5}, "latest_scan": None}
    stats = response["stats"]
    raw_latest = stats.get("latest_scan") or response.get("latest_scan")
    latest_scan = raw_latest if isinstance(raw_latest, dict) else {}
    assert latest_scan == {}
