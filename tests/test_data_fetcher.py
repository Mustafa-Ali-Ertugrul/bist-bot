"""Data fetcher helper tests."""

from __future__ import annotations

import os
import sys

import pytest
from dataclasses import replace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def test_parse_tr_number():
    """Parse Turkish number formatting correctly."""
    from data_fetcher import _parse_tr_number

    assert _parse_tr_number("1.234,56") == pytest.approx(1234.56)
    assert _parse_tr_number("100,00") == pytest.approx(100.0)
    assert _parse_tr_number("0,01") == pytest.approx(0.01)
    assert _parse_tr_number("%12,50") == pytest.approx(12.5)
    assert _parse_tr_number("abc") is None


def test_rate_limiter_initializes_request_store():
    """Rate limiter should start with an empty request registry."""
    from data_fetcher import RateLimiter

    limiter = RateLimiter()

    assert isinstance(limiter.last_request, dict)
    assert limiter.last_request == {}


def test_rate_limiter_waits_when_called_too_soon(monkeypatch):
    """Rate limiter should sleep when the same domain is hit too quickly."""
    import data_fetcher

    limiter = data_fetcher.RateLimiter()
    sleep_calls: list[float] = []
    clock = iter([100.0, 100.0, 101.0, 101.0, 103.0])

    monkeypatch.setattr(data_fetcher, "settings", replace(data_fetcher.settings, RATE_LIMIT_SECONDS=2.0))
    monkeypatch.setattr(data_fetcher.time, "time", lambda: next(clock))
    monkeypatch.setattr(data_fetcher.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    limiter.wait_if_needed("borsaistanbul.com.tr")
    limiter.wait_if_needed("borsaistanbul.com.tr")

    assert sleep_calls == [1.0]


def test_clean_ticker_list_normalizes_and_deduplicates():
    """Ticker normalization should append .IS and remove duplicates."""
    from data_fetcher import _clean_ticker_list

    raw = ["thyao", "THYAO.IS", " asels ", "ASELS.IS", ""]

    assert _clean_ticker_list(raw) == ["THYAO.IS", "ASELS.IS"]
