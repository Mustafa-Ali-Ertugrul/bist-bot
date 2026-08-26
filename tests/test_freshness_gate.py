"""B4 — candle freshness gate tests (stale data ile sinyal üretilmez)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

import bist_bot.scanner as scanner_module
from bist_bot.scanner import ScanService


def _frames(ticker_last_bar_minutes_ago: dict[str, float]) -> dict[str, dict[str, pd.DataFrame]]:
    now = pd.Timestamp.now(tz="UTC")
    data: dict[str, dict[str, pd.DataFrame]] = {}
    for ticker, age_min in ticker_last_bar_minutes_ago.items():
        idx = [now - pd.Timedelta(minutes=age_min), now - pd.Timedelta(minutes=age_min + 15)]
        trigger = pd.DataFrame({"open": [1.0, 1.0], "close": [1.0, 1.0]}, index=pd.DatetimeIndex(idx))
        trend = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.DatetimeIndex([now, now]))
        data[ticker] = {"trigger": trigger, "trend": trend}
    return data


def _service(notifier=None, warn=0.2, halt=0.4, max_age=30):
    service = ScanService.__new__(ScanService)
    service.settings = SimpleNamespace(
        STALE_BAR_MAX_AGE_MINUTES=max_age,
        STALE_SYMBOL_WARN_RATIO=warn,
        STALE_SYMBOL_HALT_RATIO=halt,
    )
    service.notifier = notifier or MagicMock()
    service._last_stale_warn_date = None
    return service


def test_fresh_bars_pass_through(monkeypatch):
    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: True)
    svc = _service()
    data = _frames({"A.IS": 5, "B.IS": 10})
    out = svc._apply_freshness_gate(data)
    assert set(out) == {"A.IS", "B.IS"}


def test_stale_ticker_dropped_during_market_hours(monkeypatch):
    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: True)
    svc = _service()
    frames = {f"T{i}.IS": 5 for i in range(9)}
    frames["OLD.IS"] = 300  # 5 saat eski → atilir (oran 0.1, warn alti)
    data = _frames(frames)
    out = svc._apply_freshness_gate(data)
    assert "OLD.IS" not in out
    assert len(out) == 9
    svc.notifier.send_message.assert_not_called()


def test_stale_ratio_halt_aborts_scan_with_alert(monkeypatch):
    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: True)
    notifier = MagicMock()
    svc = _service(notifier=notifier)
    data = _frames({f"T{i}.IS": 5 for i in range(6)} | {f"S{i}.IS": 600 for i in range(4)})
    out = svc._apply_freshness_gate(data)
    assert out == {}  # halt: sinyal uretilmez
    notifier.send_message.assert_called_once()
    assert "durduruldu" in notifier.send_message.call_args.args[0]


def test_stale_ratio_warn_band_filters_and_dedups(monkeypatch):
    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: True)
    notifier = MagicMock()
    svc = _service(notifier=notifier)
    # 2/10 = 0.2 → warn band (halt 0.4 alti).
    data = _frames({f"T{i}.IS": 5 for i in range(8)} | {f"S{i}.IS": 600 for i in range(2)})
    out = svc._apply_freshness_gate(data)
    assert len(out) == 8
    assert notifier.send_message.call_count == 1

    # Ayni gun ikinci kosu → spam yok.
    data2 = _frames({f"T{i}.IS": 5 for i in range(8)} | {f"S{i}.IS": 600 for i in range(2)})
    out2 = svc._apply_freshness_gate(data2)
    assert len(out2) == 8
    assert notifier.send_message.call_count == 1


def test_no_filtering_outside_market_hours(monkeypatch):
    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: False)
    svc = _service()
    data = _frames({"OLD1.IS": 6000, "OLD2.IS": 9999})
    out = svc._apply_freshness_gate(data)
    assert set(out) == {"OLD1.IS", "OLD2.IS"}


def test_last_bar_age_handles_date_column():
    svc = _service()
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame(
        {"close": [1.0]},
        index=pd.DatetimeIndex([0]),  # anlamsiz index
    )
    df["date"] = [now - pd.Timedelta(minutes=45)]
    age = svc._last_bar_age_minutes(df)
    assert age is not None and 40 < age < 50
