"""Paper trade service tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import bist_bot.services.paper_trade_service as paper_trade_module  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.services.paper_trade_service import PaperTradeService  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


def test_paper_trade_service_updates_open_trades():
    fetcher = MagicMock()
    db = MagicMock()
    fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 94.0]})}
    db.get_open_paper_trades.return_value = [
        SimpleNamespace(id=1, ticker="THYAO.IS", stop_loss=95.0, target_price=110.0),
    ]
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))

    service.update_open_trades()

    db.update_all_paper_close.assert_not_called()
    db.close_paper_trade.assert_called_once_with("THYAO.IS", 94.0, "STOP_HIT")


def test_paper_trade_service_closes_target_hit():
    fetcher = MagicMock()
    db = MagicMock()
    fetcher.fetch_all.return_value = {"THYAO.IS": pd.DataFrame({"close": [100.0, 111.0]})}
    db.get_open_paper_trades.return_value = [
        SimpleNamespace(id=1, ticker="THYAO.IS", stop_loss=95.0, target_price=110.0),
    ]
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))

    service.update_open_trades()

    db.update_all_paper_close.assert_not_called()
    db.close_paper_trade.assert_called_once_with("THYAO.IS", 111.0, "TARGET_HIT")


def test_paper_trade_service_keeps_trade_open_without_stop_or_target_hit():
    fetcher = MagicMock()
    db = MagicMock()
    fetcher.fetch_single.return_value = pd.DataFrame({"close": [100.0, 104.0]})
    db.get_open_paper_trades.return_value = [
        SimpleNamespace(id=1, ticker="THYAO.IS", stop_loss=95.0, target_price=110.0),
    ]
    service = PaperTradeService(fetcher, db, settings=settings.replace(PAPER_MODE=True))

    service.update_open_trades()

    db.update_all_paper_close.assert_not_called()
    db.close_paper_trade.assert_not_called()


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
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )

    service.queue_actionable_signals([signal])

    db.add_paper_trade.assert_called_once_with(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY.value,
        signal_price=100.0,
        signal_time=datetime(2025, 1, 1, 10, 0, 0),
        stop_loss=95.0,
        target_price=110.0,
        score=25,
        regime="TRENDING",
    )
