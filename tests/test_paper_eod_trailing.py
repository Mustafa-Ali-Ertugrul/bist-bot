"""Faz 3 P1/P2 tests: paper EOD close discipline + trailing stop.

P1 contract (mirrors SignalOutcomeTracker._is_eod):
- after bist_close_time(date) every open paper position closes with EOD_CLOSE
- half-day dates close at 12:30 TR, holidays/weekends never trigger
- before close time the position stays open

P2 contract:
- TRAILING_STOP_ENABLED=True ratchets an in-memory extreme seeded at entry
- long: trail = extreme * (1 - PCT/100), only tightens upward
- short: trail = extreme * (1 + PCT/100), only tightens downward
- crossing the trail closes with TRAIL_STOP_HIT; original STOP_HIT wins first
- disabled (default) -> no behavior change
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import bist_bot.market_calendar as market_calendar  # noqa: E402
from bist_bot.services.paper_trade_service import PaperTradeService  # noqa: E402
from bist_bot.strategy.signal_models import SignalType  # noqa: E402


def _make_trade(
    *,
    ticker: str = "THYAO.IS",
    signal_type: str = SignalType.BUY.value,
    signal_price: float = 100.0,
    stop_loss: float | None = 95.0,
    target_price: float | None = 110.0,
    direction: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        ticker=ticker,
        signal_type=signal_type,
        signal_price=signal_price,
        stop_loss=stop_loss,
        target_price=target_price,
        direction=direction,
    )


def _service(db, *, trailing: bool = False, pct: float = 2.0) -> PaperTradeService:
    fetcher = MagicMock()
    fetcher.fetch_all.return_value = {}
    cfg = SimpleNamespace(
        PAPER_MODE=True,
        TRAILING_STOP_ENABLED=trailing,
        TRAILING_STOP_PCT=pct,
        PAPER_COOLDOWN_DAYS=0,
    )
    return PaperTradeService(fetcher, db, settings=cfg)


def _price_service(db, ticker: str, price: float, **kwargs) -> PaperTradeService:
    service = _service(db, **kwargs)
    service.fetcher.fetch_all.return_value = {ticker: pd.DataFrame({"close": [100.0, price]})}
    return service


# ---------------------------------------------------------------------------
# P1 — EOD close discipline
# ---------------------------------------------------------------------------


def test_paper_eod_close_after_market_close():
    """17:31 TR on a full trading day -> position closes with EOD_CLOSE."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    # 2026-08-20 is a Thursday; 14:31 UTC == 17:31 TR (after 17:30 close)
    now = datetime(2026, 8, 20, 14, 31, tzinfo=UTC)
    service = _price_service(db, "THYAO.IS", 104.0)  # between stop 95 / target 110

    service.update_open_trades(now=now)

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 104.0, "EOD_CLOSE", actual_profit_pct=ANY
    )


def test_paper_eod_half_day_closes_at_1230():
    """Known half-day date injected into the calendar -> closes at 12:31 TR."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    half_day = datetime(2026, 8, 21, tzinfo=UTC).date()  # Friday test fixture date
    now = datetime(2026, 8, 21, 9, 31, tzinfo=UTC)  # 12:31 TR
    service = _price_service(db, "THYAO.IS", 104.0)

    monkey_half_day = pytest.MonkeyPatch()
    try:
        monkey_half_day.setattr(market_calendar, "_HALF_DAY_DATES", {half_day}, raising=False)
        service.update_open_trades(now=now)
    finally:
        monkey_half_day.undo()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 104.0, "EOD_CLOSE", actual_profit_pct=ANY
    )


def test_paper_no_eod_before_market_close():
    """17:29 TR -> position stays open (no close call)."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    now = datetime(2026, 8, 20, 14, 29, tzinfo=UTC)  # 17:29 TR
    service = _price_service(db, "THYAO.IS", 104.0)

    service.update_open_trades(now=now)

    db.close_paper_trade.assert_not_called()


def test_paper_no_eod_on_weekend():
    """Weekend is a holiday -> no EOD trigger even after close time."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    now = datetime(2026, 8, 22, 14, 31, tzinfo=UTC)  # Saturday 17:31 TR
    service = _price_service(db, "THYAO.IS", 104.0)

    service.update_open_trades(now=now)

    db.close_paper_trade.assert_not_called()


def test_eod_priority_after_stop_hit():
    """Stop hit and EOD same tick -> STOP_HIT wins (conservative order)."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]  # stop 95
    now = datetime(2026, 8, 20, 14, 31, tzinfo=UTC)
    service = _price_service(db, "THYAO.IS", 94.0)  # breaches stop

    service.update_open_trades(now=now)

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 94.0, "STOP_HIT", actual_profit_pct=ANY
    )


# ---------------------------------------------------------------------------
# P2 — Trailing stop
# ---------------------------------------------------------------------------


def test_trailing_tightens_stop_on_rise_long():
    """Rise ratchets the trail; falling back through it closes TRAIL_STOP_HIT."""
    db = MagicMock()
    trade = _make_trade(signal_price=100.0, stop_loss=95.0, target_price=110.0)
    db.get_open_paper_trades.return_value = [trade]
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    service = _service(db, trailing=True, pct=2.0)
    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 104.0]})}

    service.update_open_trades(now=now)  # watermark 104 -> trail 101.92; open
    db.close_paper_trade.assert_not_called()

    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 101.0]})}
    service.update_open_trades(now=now)  # 101 <= 101.92 -> trail hit

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 101.0, "TRAIL_STOP_HIT", actual_profit_pct=ANY
    )


def test_trailing_never_loosens_on_fall_long():
    """After a rise, a deeper fall must NOT recalculate the trail downward."""
    db = MagicMock()
    trade = _make_trade(signal_price=100.0, stop_loss=95.0, target_price=110.0)
    db.get_open_paper_trades.return_value = [trade]
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    service = _service(db, trailing=True, pct=2.0)
    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 108.0]})}

    service.update_open_trades(now=now)  # watermark 108 -> trail 105.84

    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 103.0]})}
    service.update_open_trades(now=now)  # trail stays 105.84 (not 103-based)

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 103.0, "TRAIL_STOP_HIT", actual_profit_pct=ANY
    )


def test_trailing_short_mirror():
    """Short: falling price ratchets the trail down; bounce closes it."""
    db = MagicMock()
    trade = _make_trade(
        signal_type=SignalType.SELL.value,
        signal_price=100.0,
        stop_loss=105.0,
        target_price=90.0,
        direction="short",
    )
    db.get_open_paper_trades.return_value = [trade]
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    service = _service(db, trailing=True, pct=2.0)
    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 96.0]})}

    service.update_open_trades(now=now)  # low-water 96 -> trail 97.92; open
    db.close_paper_trade.assert_not_called()

    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 98.0]})}
    service.update_open_trades(now=now)  # 98 >= 97.92 -> trail hit

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 98.0, "TRAIL_STOP_HIT", actual_profit_pct=ANY
    )


def test_trailing_disabled_is_noop():
    """Default (disabled): identical price path never closes via trail."""
    db = MagicMock()
    trade = _make_trade(signal_price=100.0, stop_loss=95.0, target_price=110.0)
    db.get_open_paper_trades.return_value = [trade]
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    service = _service(db, trailing=False, pct=2.0)
    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 104.0]})}

    service.update_open_trades(now=now)
    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 101.0]})}
    service.update_open_trades(now=now)  # would be a trail hit if enabled

    db.close_paper_trade.assert_not_called()


def test_original_stop_wins_over_trail():
    """Breaching the ORIGINAL stop reports STOP_HIT, not TRAIL_STOP_HIT."""
    db = MagicMock()
    trade = _make_trade(signal_price=100.0, stop_loss=95.0, target_price=110.0)
    db.get_open_paper_trades.return_value = [trade]
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    service = _service(db, trailing=True, pct=2.0)
    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 108.0]})}

    service.update_open_trades(now=now)  # watermark 108

    service.fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 94.0]})}
    service.update_open_trades(now=now)  # 94 <= original stop 95

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 94.0, "STOP_HIT", actual_profit_pct=ANY
    )
