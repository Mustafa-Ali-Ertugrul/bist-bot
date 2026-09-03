"""Paper trade service tests.

Covers the directional lifecycle contract:
- long:  stop when price <= stop, target when price >= target
- short: stop when price >= stop, target when price <= target
- stop wins over target when both are crossed (conservative, matches backtest)
- direction-aware net PnL and close with actual_profit_pct
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import bist_bot.services.paper_trade_service as paper_trade_module  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.risk.costs import TradingCosts  # noqa: E402
from bist_bot.services.paper_trade_service import (  # noqa: E402
    PaperTradeService,
    paper_direction_from_signal_type,
)
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


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


def _service_with_close_price(db, ticker: str, price: float, costs: TradingCosts | None = None):
    fetcher = MagicMock()
    fetcher.fetch_all.return_value = {ticker: pd.DataFrame({"close": [100.0, price]})}
    return PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True), costs=costs)


def test_paper_trade_service_updates_open_trades():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    service = _service_with_close_price(db, "THYAO.IS", 94.0)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        94.0,
        "STOP_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_paper_trade_service_closes_target_hit():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    service = _service_with_close_price(db, "THYAO.IS", 111.0)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        111.0,
        "TARGET_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_paper_trade_service_keeps_trade_open_without_stop_or_target_hit():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade()]
    service = _service_with_close_price(db, "THYAO.IS", 104.0)

    service.update_open_trades(now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC))  # mid-session TR

    db.close_paper_trade.assert_not_called()


# ---------------------------------------------------------------------------
# Short direction lifecycle
# ---------------------------------------------------------------------------


def test_short_trade_closes_when_price_rises_to_stop():
    """Short stop hits when price >= stop_loss."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_type=SignalType.SELL.value,
            stop_loss=105.0,
            target_price=90.0,
            direction="short",
        )
    ]
    service = _service_with_close_price(db, "THYAO.IS", 105.5)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        105.5,
        "STOP_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_short_trade_closes_when_price_falls_to_target():
    """Short target hits when price <= target_price."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_type=SignalType.SELL.value,
            stop_loss=105.0,
            target_price=90.0,
            direction="short",
        )
    ]
    service = _service_with_close_price(db, "THYAO.IS", 89.5)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        89.5,
        "TARGET_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_short_trade_stays_open_between_levels():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_type=SignalType.SELL.value,
            stop_loss=105.0,
            target_price=90.0,
            direction="short",
        )
    ]
    service = _service_with_close_price(db, "THYAO.IS", 97.0)

    service.update_open_trades(now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC))  # mid-session TR

    db.close_paper_trade.assert_not_called()


def test_stop_wins_over_target_when_both_crossed():
    """Same-bar ambiguity resolved conservatively: stop exits first."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade(stop_loss=95.0, target_price=104.0)]
    service = _service_with_close_price(db, "THYAO.IS", 94.0)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        94.0,
        "STOP_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_legacy_rows_fallback_to_signal_type_direction():
    """Rows persisted before the direction column exist fall back to signal type."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_type=SignalType.STRONG_SELL.value,
            stop_loss=105.0,
            target_price=90.0,
            direction=None,
        )
    ]
    service = _service_with_close_price(db, "THYAO.IS", 89.0)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        89.0,
        "TARGET_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )
    assert paper_direction_from_signal_type(SignalType.STRONG_SELL.value) == "short"
    assert paper_direction_from_signal_type("not-a-signal") == "long"


# ---------------------------------------------------------------------------
# Direction-aware opposite signal exits
# ---------------------------------------------------------------------------


def test_long_trade_closes_on_strong_sell_signal():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade(direction="long")]
    service = _service_with_close_price(db, "THYAO.IS", 103.0)
    opposing = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.SELL,
        score=-30.0,
        price=103.0,
    )

    service.update_open_trades(signals=[opposing])

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        103.0,
        "OPPOSITE_SIGNAL",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_long_trade_ignores_weak_opposite_signal_below_threshold():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_make_trade(direction="long")]
    service = _service_with_close_price(db, "THYAO.IS", 103.0)
    weak_opposing = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.WEAK_SELL,
        score=-10.0,
        price=103.0,
    )

    service.update_open_trades(
        signals=[weak_opposing], now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    )  # mid-session TR

    db.close_paper_trade.assert_not_called()


def test_short_trade_closes_on_strong_buy_signal():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_type=SignalType.SELL.value,
            stop_loss=105.0,
            target_price=90.0,
            direction="short",
        )
    ]
    service = _service_with_close_price(db, "THYAO.IS", 97.0)
    opposing = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=40.0,
        price=97.0,
    )

    service.update_open_trades(signals=[opposing])

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        97.0,
        "OPPOSITE_SIGNAL",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )


def test_short_trade_ignores_buy_signal_below_threshold():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_type=SignalType.SELL.value,
            stop_loss=105.0,
            target_price=90.0,
            direction="short",
        )
    ]
    service = _service_with_close_price(db, "THYAO.IS", 97.0)
    weak = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.WEAK_BUY,
        score=10.0,
        price=97.0,
    )

    service.update_open_trades(
        signals=[weak], now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    )  # mid-session TR

    db.close_paper_trade.assert_not_called()


# ---------------------------------------------------------------------------
# Direction-aware net profit
# ---------------------------------------------------------------------------


def test_net_profit_pct_long_positive_and_negative():
    zero_costs = TradingCosts(commission_pct=0.0, stamp_tax_pct=0.0, bsmv_pct=0.0)
    assert PaperTradeService.net_profit_pct(100.0, 110.0, zero_costs, "long") == 10.0
    assert PaperTradeService.net_profit_pct(100.0, 90.0, zero_costs, "long") == -10.0


def test_net_profit_pct_short_sign_is_inverted():
    zero_costs = TradingCosts(commission_pct=0.0, stamp_tax_pct=0.0, bsmv_pct=0.0)
    assert PaperTradeService.net_profit_pct(100.0, 90.0, zero_costs, "short") == 10.0
    assert PaperTradeService.net_profit_pct(100.0, 110.0, zero_costs, "short") == -10.0


def test_close_records_direction_aware_profit_with_costs():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(
            signal_price=100.0,
            stop_loss=95.0,
            target_price=110.0,
            direction="long",
        )
    ]
    zero_costs = TradingCosts(commission_pct=0.0, stamp_tax_pct=0.0, bsmv_pct=0.0)
    service = _service_with_close_price(db, "THYAO.IS", 111.0, costs=zero_costs)

    service.update_open_trades()

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS", 111.0, "TARGET_HIT", actual_profit_pct=11.0, trade_id=ANY
    )


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------


def test_paper_trade_service_queues_actionable_signals(monkeypatch):
    fetcher = MagicMock()
    db = MagicMock()
    monkeypatch.setattr(
        paper_trade_module, "detect_regime", lambda _df: SimpleNamespace(value="TRENDING")
    )
    fetcher.fetch_single.return_value = pd.DataFrame({"close": [100.0, 101.0]})
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )

    service.queue_actionable_signals([signal])

    db.add_paper_trade.assert_called_once_with(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY.value,
        signal_price=100.0,
        signal_time=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        stop_loss=95.0,
        target_price=110.0,
        score=25,
        regime="TRENDING",
        direction="long",
    )


def test_queue_actionable_sell_signal_records_short_direction(monkeypatch):
    fetcher = MagicMock()
    db = MagicMock()
    monkeypatch.setattr(
        paper_trade_module, "detect_regime", lambda _df: SimpleNamespace(value="TRENDING")
    )
    fetcher.fetch_single.return_value = pd.DataFrame({"close": [100.0, 99.0]})
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.SELL,
        score=-30.0,
        price=100.0,
        stop_loss=105.0,
        target_price=90.0,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )

    service.queue_actionable_signals([signal])

    _, kwargs = db.add_paper_trade.call_args
    assert kwargs["direction"] == "short"


# ---------------------------------------------------------------------------
# F3: scan price priority (zero-latency) + fetch fallback
# ---------------------------------------------------------------------------


def test_update_open_trades_prefers_scan_price_over_fetch():
    """Scan signals are the primary price source; fetch is fallback only."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(ticker="THYAO.IS", stop_loss=95.0, target_price=110.0, signal_price=100.0),
        _make_trade(ticker="GARAN.IS", stop_loss=48.0, target_price=55.0, signal_price=50.0),
    ]
    # Fetcher would return non-triggering prices if used (105 for THYAO would NOT hit stop)
    fetcher = MagicMock()
    fetcher.fetch_all.return_value = {
        "THYAO.IS": pd.DataFrame({"close": [105.0]}),
        "GARAN.IS": pd.DataFrame({"close": [48.0]}),
    }
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))
    signals = [
        Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=30, price=94.0),
        Signal(ticker="GARAN.IS", signal_type=SignalType.BUY, score=30, price=54.0),
    ]

    service.update_open_trades(
        signals=signals, now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    )  # mid-session TR

    # THYAO 94 <= 95 → STOP_HIT via scan price (not fetcher 105); GARAN 54 stays open (48 <54 <55)
    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        94.0,
        "STOP_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )
    # fetcher.fetch_all should NOT have been needed for THYAO/GARAN (both in signals), so either not called or called only for missing
    # In this case both tickers are in signals → missing==[] → fetch_all not called
    fetcher.fetch_all.assert_not_called()


def test_update_open_trades_fetches_only_missing_tickers():
    """Only tickers missing from scan signals are fetched."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(ticker="THYAO.IS", stop_loss=95.0, target_price=110.0, signal_price=100.0),
        _make_trade(ticker="ASELS.IS", stop_loss=78.0, target_price=88.0, signal_price=80.0),
    ]
    fetcher = MagicMock()
    fetcher.fetch_all.return_value = {
        "ASELS.IS": pd.DataFrame({"close": [77.0]}),
    }
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))
    signals = [
        Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=30, price=94.0),
    ]

    service.update_open_trades(signals=signals)

    # THYAO via scan 94 → STOP_HIT, ASELS via fetch 77 → STOP_HIT
    assert db.close_paper_trade.call_count == 2
    calls = {c.args[0]: c.args for c in db.close_paper_trade.call_args_list}
    assert calls["THYAO.IS"][1] == 94.0
    assert calls["ASELS.IS"][1] == 77.0
    fetcher.fetch_all.assert_called_once()


def test_update_open_trades_fallback_when_no_signals():
    """signals=None → all prices via fetch fallback (documented fallback)."""
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _make_trade(ticker="THYAO.IS", stop_loss=95.0, target_price=110.0, signal_price=100.0),
    ]
    fetcher = MagicMock()
    fetcher.fetch_all.return_value = {
        "THYAO.IS": pd.DataFrame({"close": [111.0]}),
    }
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))

    service.update_open_trades(signals=None)

    db.close_paper_trade.assert_called_once_with(
        "THYAO.IS",
        111.0,
        "TARGET_HIT",
        actual_profit_pct=ANY,
        trade_id=ANY,
    )
    fetcher.fetch_all.assert_called_once()
