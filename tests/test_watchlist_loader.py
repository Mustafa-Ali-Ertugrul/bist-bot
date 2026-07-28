"""Tests for dynamic watchlist loading and scanner integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bist_bot.config.watchlist import (
    BIST30_TICKERS,
    load_watchlist,
    resolve_watchlist_source,
    robust_watchlist_path,
)
from bist_bot.scanner import ScanService


def test_resolve_watchlist_source_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHLIST_SOURCE", "bist30")
    assert resolve_watchlist_source(None) == "bist30"
    assert resolve_watchlist_source("robust") == "bist30"
    monkeypatch.setenv("BIST_BOT_WATCHLIST_SOURCE", "bist100")
    monkeypatch.delenv("WATCHLIST_SOURCE", raising=False)
    assert resolve_watchlist_source(None) == "bist100"


def test_load_watchlist_bist30() -> None:
    tickers = load_watchlist("bist30")
    assert tickers == list(BIST30_TICKERS)
    assert "THYAO.IS" in tickers
    assert len(tickers) == 30


def test_load_watchlist_robust_from_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "robust_watchlist.csv"
    csv_path.write_text(
        "ticker,stress_oos_mean_return\nSISE.IS,5.9\nTHYAO.IS,0.4\nASTOR.IS,5.6\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WATCHLIST_ROBUST_PATH", str(csv_path))
    tickers = load_watchlist("robust")
    assert tickers == ["SISE.IS", "THYAO.IS", "ASTOR.IS"]


def test_load_watchlist_file_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "custom.csv"
    csv_path.write_text("ticker\ngaran\nakbnk.is\n", encoding="utf-8")
    tickers = load_watchlist(f"file:{csv_path}")
    assert tickers == ["garan", "akbnk.is"]


def test_load_watchlist_missing_robust_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does_not_exist.csv"
    monkeypatch.setenv("WATCHLIST_ROBUST_PATH", str(missing))
    tickers = load_watchlist("robust")
    assert tickers == []


def test_load_watchlist_empty_csv_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("ticker\n", encoding="utf-8")
    monkeypatch.setenv("WATCHLIST_ROBUST_PATH", str(empty))
    tickers = load_watchlist("robust")
    assert tickers == []


def test_robust_watchlist_path_default_points_to_results() -> None:
    path = robust_watchlist_path()
    assert path.name == "robust_watchlist.csv"
    assert "results" in path.parts


def test_scanner_aborts_when_watchlist_empty() -> None:
    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    empty_settings = MagicMock()
    empty_settings.WATCHLIST = []
    empty_settings.WATCHLIST_SOURCE = "robust"
    empty_settings.PAPER_MODE = False
    empty_settings.MTF_TREND_PERIOD = "6mo"
    empty_settings.MTF_TREND_INTERVAL = "1d"
    empty_settings.MTF_TRIGGER_PERIOD = "1mo"
    empty_settings.MTF_TRIGGER_INTERVAL = "15m"

    service = ScanService(fetcher, engine, notifier, db, settings=empty_settings)
    result = service.scan_once()

    assert result == []
    fetcher.fetch_multi_timeframe_all.assert_not_called()
    assert service.last_scan_stats["scanned"] == 0


def test_scanner_uses_settings_watchlist_on_fetcher() -> None:
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {}
    fetcher.get_last_skipped_tickers.return_value = []
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    settings_obj = MagicMock()
    settings_obj.WATCHLIST = ["SISE.IS", "THYAO.IS"]
    settings_obj.WATCHLIST_SOURCE = "robust"
    settings_obj.PAPER_MODE = False
    settings_obj.MTF_TREND_PERIOD = "6mo"
    settings_obj.MTF_TREND_INTERVAL = "1d"
    settings_obj.MTF_TRIGGER_PERIOD = "1mo"
    settings_obj.MTF_TRIGGER_INTERVAL = "15m"

    service = ScanService(fetcher, engine, notifier, db, settings=settings_obj)
    service.scan_once()

    assert fetcher.watchlist == ["SISE.IS", "THYAO.IS"]
    fetcher.fetch_multi_timeframe_all.assert_called_once()
