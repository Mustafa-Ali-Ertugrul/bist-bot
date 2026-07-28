"""End-to-end integration / regression tests for the data layer.

WARNING / UYARI
---------------
If you intentionally change provider retry/timeout budgets, history cache TTL
(``FETCH_CACHE_TTL_SECONDS`` / ``INTRADAY_FETCH_CACHE_TTL_SECONDS``),
normalize/validate schema rules, multi-timeframe skip tracking, or SQLite
signal persistence shape, you MUST consciously update the expected cache
call counts, skip lists, and repository payloads in this file.

Bu dosya, strateji/risk/backtest'in beslendiği veri katmanının dayanıklı
çalıştığını garanti eder:

1. ``BISTDataFetcher`` + injected provider + in-memory TTL cache
2. ``OfficialProvider`` graceful degradation (429 / timeout → ``None``)
3. Multi-timeframe skip tracking (``get_last_skipped_tickers``)
4. SQLite signal persistence (``SignalsRepository`` / ``DatabaseManager``)

PostgreSQL/TimescaleDB is not required for local integration; when
``DATABASE_URL`` is unset the project uses SQLite. A live Postgres check is
skipped unless explicitly configured.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest

from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.data.providers import (
    OfficialProvider,
    RequestsOfficialHTTPClient,
)
from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.signal_models import Signal, SignalType


def _ohlcv_frame(
    *,
    close: float = 100.0,
    periods: int = 10,
    start: str = "2025-01-01",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [close] * periods,
            "high": [close + 1.0] * periods,
            "low": [close - 1.0] * periods,
            "close": [close + 0.5] * periods,
            "volume": [1_000.0] * periods,
        },
        index=pd.date_range(start, periods=periods),
    )


class CountingProvider:
    """Injectable market-data provider that counts history/batch calls."""

    def __init__(self, frames: dict[str, pd.DataFrame | None] | None = None) -> None:
        self.frames = frames or {}
        self.history_calls: list[tuple[str, str, str]] = []
        self.batch_calls: list[tuple[tuple[str, ...], str, str]] = []
        self.raise_on_history: Exception | None = None

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        self.history_calls.append((ticker, period, interval))
        if self.raise_on_history is not None:
            raise self.raise_on_history
        frame = self.frames.get(ticker)
        return None if frame is None else frame.copy()

    def fetch_batch(
        self, tickers: list[str], period: str, interval: str
    ) -> dict[str, pd.DataFrame | None]:
        self.batch_calls.append((tuple(tickers), period, interval))
        out: dict[str, pd.DataFrame | None] = {}
        for ticker in tickers:
            frame = self.frames.get(ticker)
            out[ticker] = None if frame is None else frame.copy()
        return out

    def fetch_quote(self, ticker: str) -> float | None:
        _ = ticker
        return None

    def fetch_universe(self, force_refresh: bool = False) -> list[str]:
        _ = force_refresh
        return list(self.frames.keys()) or ["THYAO.IS"]


class NullQuoteProvider:
    def fetch_quote(self, ticker: str) -> float | None:
        _ = ticker
        return None


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_body: dict | None = None,
        text: str = "",
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict:
        return self._json


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("POST", url))
        return self.responses.pop(0)

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, url))
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------


def test_normal_fetch_stores_history_in_cache_and_returns_frame() -> None:
    """Normal çekim: provider success → normalized frame + cache meta."""
    provider = CountingProvider({"THYAO.IS": _ohlcv_frame(close=250.0)})
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )

    frame = fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d", force=True)

    assert frame is not None
    assert len(frame) >= 5
    assert "close" in frame.columns
    assert provider.history_calls == [("THYAO.IS", "1mo", "1d")]
    meta = fetcher.get_last_history_fetch_meta("THYAO.IS", "1mo", "1d")
    assert meta is not None
    assert meta["source"] == "single"
    assert meta["status"] == "success"


def test_cache_hit_skips_provider_on_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Önbellek hit: aynı sembol TTL içinde tekrar istenince provider çağrılmaz."""
    provider = CountingProvider({"THYAO.IS": _ohlcv_frame()})
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )
    clock = [pd.Timestamp("2025-06-01 10:00:00").to_pydatetime()]
    monkeypatch.setattr(fetcher, "_now", lambda: clock[0])

    first = fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d")
    clock[0] = pd.Timestamp("2025-06-01 10:01:00").to_pydatetime()
    second = fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d")

    assert first is not None and second is not None
    assert provider.history_calls == [("THYAO.IS", "1mo", "1d")]
    meta = fetcher.get_last_history_fetch_meta("THYAO.IS", "1mo", "1d")
    assert meta == {"source": "cache", "status": "success"}


def test_cache_miss_after_ttl_calls_provider_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Önbellek miss: daily TTL (default 900s) aşılınca provider yeniden çağrılır."""
    provider = CountingProvider({"THYAO.IS": _ohlcv_frame()})
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )
    clock = [pd.Timestamp("2025-06-01 10:00:00").to_pydatetime()]
    monkeypatch.setattr(fetcher, "_now", lambda: clock[0])
    # Force a short daily TTL for the test without depending on env.
    monkeypatch.setattr(fetcher, "_history_ttl", lambda _interval: pd.Timedelta(seconds=60))

    fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d")
    clock[0] = pd.Timestamp("2025-06-01 10:02:00").to_pydatetime()  # > 60s
    fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d")

    assert len(provider.history_calls) == 2


def test_force_refresh_bypasses_fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CountingProvider({"THYAO.IS": _ohlcv_frame()})
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )
    clock = [pd.Timestamp("2025-06-01 10:00:00").to_pydatetime()]
    monkeypatch.setattr(fetcher, "_now", lambda: clock[0])

    fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d")
    fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d", force=True)

    assert len(provider.history_calls) == 2


def test_different_ticker_is_cache_miss() -> None:
    provider = CountingProvider(
        {
            "THYAO.IS": _ohlcv_frame(close=100.0),
            "GARAN.IS": _ohlcv_frame(close=80.0),
        }
    )
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS", "GARAN.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )

    fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d", force=True)
    fetcher.fetch_single("GARAN.IS", period="1mo", interval="1d", force=True)

    assert [call[0] for call in provider.history_calls] == ["THYAO.IS", "GARAN.IS"]


# ---------------------------------------------------------------------------
# Graceful degradation / OfficialProvider
# ---------------------------------------------------------------------------


def test_provider_exception_returns_none_without_raising() -> None:
    """Ağ/provider hatası exception fırlatmaz; None + log path."""
    provider = CountingProvider({"THYAO.IS": _ohlcv_frame()})
    provider.raise_on_history = ConnectionError("network down")
    # Batch fallback also empty/raises path → None
    provider.frames["THYAO.IS"] = None
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )

    result = fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d", force=True)
    assert result is None


def test_corrupt_provider_payload_returns_none() -> None:
    """Bozuk şema (eksik OHLCV kolonları) → validate fail → None, no crash."""
    bad = pd.DataFrame({"foo": [1, 2, 3]})
    provider = CountingProvider({"THYAO.IS": bad})
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )

    result = fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d", force=True)
    assert result is None


def test_official_provider_rate_limit_exhaustion_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OfficialProvider 429 + max retries → fetch_history returns None (graceful)."""
    session = _FakeSession(
        [
            _FakeResponse(200, {"token": "tok"}),
            _FakeResponse(429, text="slow down", headers={"Retry-After": "1"}),
            _FakeResponse(429, text="slow down", headers={"Retry-After": "1"}),
        ]
    )
    provider = OfficialProvider(
        base_url="https://api.example.com",
        api_key="k",
        username="u",
        password="p",
        timeout=1.0,
        max_retries=2,
        retry_backoff=0.01,
        max_retry_sleep=0.01,
        http_client=RequestsOfficialHTTPClient(session=session),
    )
    monkeypatch.setattr("bist_bot.data.providers.time.sleep", lambda _s: None)

    frame = provider.fetch_history("THYAO.IS", "1mo", "1d")
    assert frame is None


def test_official_provider_success_through_fetcher() -> None:
    """OfficialProvider happy path → BISTDataFetcher normalizes and caches."""
    records = [
        {
            "date": f"2025-01-{i + 1:02d}",
            "open": 10 + i,
            "high": 11 + i,
            "low": 9 + i,
            "close": 10.5 + i,
            "volume": 1000 + i,
        }
        for i in range(8)
    ]
    session = _FakeSession(
        [
            _FakeResponse(200, {"token": "tok"}),
            _FakeResponse(200, {"data": records}),
        ]
    )
    official = OfficialProvider(
        base_url="https://api.example.com",
        api_key="k",
        username="u",
        password="p",
        timeout=2.0,
        max_retries=2,
        retry_backoff=0.01,
        http_client=RequestsOfficialHTTPClient(session=session),
    )
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS"],
        provider=official,
        quote_provider=NullQuoteProvider(),
    )

    frame = fetcher.fetch_single("THYAO.IS", period="1mo", interval="1d", force=True)
    assert frame is not None
    assert len(frame) == 8
    assert set(["open", "high", "low", "close", "volume"]).issubset(frame.columns)


def test_multi_timeframe_records_skipped_tickers_for_ui_warning() -> None:
    """Partial provider failure → combined result omits ticker + skip list for UI."""
    good = _ohlcv_frame(close=120.0, periods=12)
    provider = CountingProvider({"THYAO.IS": good, "GARAN.IS": None})
    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS", "GARAN.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )

    combined = fetcher.fetch_multi_timeframe(
        ["THYAO.IS", "GARAN.IS"],
        trend_period="1mo",
        trend_interval="1d",
        trigger_period="5d",
        trigger_interval="15m",
        force_refresh=True,
    )

    assert "THYAO.IS" in combined
    assert "GARAN.IS" not in combined
    assert "GARAN.IS" in fetcher.get_last_skipped_tickers()


# ---------------------------------------------------------------------------
# Persistence (SQLite)
# ---------------------------------------------------------------------------


@pytest.fixture
def signals_repo(tmp_path):
    db_path = tmp_path / "data_layer_signals.db"
    manager = DatabaseManager(sqlite_path=str(db_path))
    repo = SignalsRepository(manager=manager)
    try:
        yield repo
    finally:
        manager.session_factory.remove()
        if hasattr(manager, "engine"):
            manager.engine.dispose()


def test_sqlite_signal_write_and_read_roundtrip(signals_repo: SignalsRepository) -> None:
    """SQLite yazma/okuma: sinyal persist edilir ve geri okunur."""
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=250.5,
        reasons=["data-layer-integration"],
        stop_loss=240.0,
        target_price=270.0,
        timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
    )
    signals_repo.save_signal(signal)

    recent = signals_repo.get_recent_signals(limit=10, ticker="THYAO.IS")
    assert recent
    latest = recent[0]
    assert latest["ticker"] == "THYAO.IS"
    assert float(latest["score"]) == pytest.approx(25.0)
    assert float(latest["price"]) == pytest.approx(250.5)


def test_sqlite_scan_log_persistence(signals_repo: SignalsRepository) -> None:
    signals_repo.save_scan_log(
        total=100,
        generated=12,
        buys=5,
        sells=3,
        actionable=4,
        scan_id="scan-data-layer",
        rejection_breakdown={
            "total_rejections": 2,
            "by_reason": [{"reason_code": "insufficient_history", "count": 2}],
            "by_stage": [{"stage": "data", "count": 2}],
            "scan_id": "scan-data-layer",
        },
    )
    logs = signals_repo.get_recent_scan_logs(limit=5)
    assert logs
    assert logs[0]["total_scanned"] == 100 or logs[0].get("total_scanned") == 100


def test_postgres_connection_skipped_without_database_url() -> None:
    """PostgreSQL/TimescaleDB path is optional; skip unless DATABASE_URL is set."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url or database_url.startswith("sqlite"):
        pytest.skip("DATABASE_URL not configured for live Postgres integration")
    # Live smoke: construct manager against configured URL.
    manager = DatabaseManager(database_url=database_url)
    try:
        assert manager.engine is not None
    finally:
        manager.session_factory.remove()
        manager.engine.dispose()


# ---------------------------------------------------------------------------
# End-to-end: fetch → optional persist metadata
# ---------------------------------------------------------------------------


def test_fetch_then_persist_signal_end_to_end(signals_repo: SignalsRepository) -> None:
    """Fetcher success + signal repository write forms the full data pipeline."""
    provider = CountingProvider({"ASELS.IS": _ohlcv_frame(close=80.0, periods=12)})
    fetcher = BISTDataFetcher(
        watchlist=["ASELS.IS"],
        provider=provider,
        quote_provider=NullQuoteProvider(),
    )
    frame = fetcher.fetch_single("ASELS.IS", period="1mo", interval="1d", force=True)
    assert frame is not None
    last_close = float(frame["close"].iloc[-1])

    signal = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.WEAK_BUY,
        score=12.0,
        price=last_close,
        reasons=["e2e-data-layer"],
        timestamp=datetime(2025, 6, 2, 9, 30, 0, tzinfo=UTC),
    )
    signals_repo.save_signal(signal)
    stored = signals_repo.get_latest_signal("ASELS.IS")
    assert stored is not None
    assert stored["ticker"] == "ASELS.IS"
    assert float(stored["price"]) == pytest.approx(last_close)
