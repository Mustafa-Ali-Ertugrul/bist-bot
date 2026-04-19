"""Backtest runner tests."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import config  # noqa: E402
from backtest_runner import run_backtest  # noqa: E402


def test_run_backtest_returns_without_crash_on_empty_watchlist(monkeypatch):
    monkeypatch.setattr(config.settings, "WATCHLIST", [], raising=False)
    fetcher = MagicMock()

    run_backtest(fetcher)


def test_run_backtest_skips_none_data(monkeypatch):
    monkeypatch.setattr(config.settings, "WATCHLIST", ["THYAO.IS"], raising=False)
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = None

    run_backtest(fetcher)
