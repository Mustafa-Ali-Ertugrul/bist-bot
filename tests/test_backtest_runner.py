"""Backtest runner tests."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import bist_bot.backtest_runner as backtest_runner_module  # noqa: E402
from bist_bot.backtest_runner import run_backtest  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402


def test_run_backtest_returns_without_crash_on_empty_watchlist(monkeypatch):
    monkeypatch.setattr(
        backtest_runner_module.config,
        "settings",
        settings.replace(WATCHLIST=[]),
    )
    fetcher = MagicMock()

    run_backtest(fetcher)


def test_run_backtest_skips_none_data(monkeypatch):
    monkeypatch.setattr(
        backtest_runner_module.config,
        "settings",
        settings.replace(WATCHLIST=["THYAO.IS"]),
    )
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = None

    run_backtest(fetcher)


def test_run_backtest_uses_historical_universe_when_requested(monkeypatch):
    monkeypatch.setattr(
        backtest_runner_module.config,
        "settings",
        settings.replace(WATCHLIST=["THYAO.IS", "ASELS.IS", "GARAN.IS"]),
    )
    monkeypatch.setattr(
        backtest_runner_module.sys,
        "argv",
        ["backtest_runner.py", "--historical-universe-date", "2023-01-01"],
    )

    fetcher = MagicMock()
    fetcher.fetch_single.return_value = None

    run_backtest(fetcher)

    fetched = [call.args[0] for call in fetcher.fetch_single.call_args_list]
    assert fetched == ["THYAO.IS", "GARAN.IS", "TUPRS.IS", "BIMAS.IS", "SAHOL.IS"]
