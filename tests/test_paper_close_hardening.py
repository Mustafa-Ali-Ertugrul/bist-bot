"""B3 — paper trade close path hardening tests.

- close_paper_trade(trade_id=...) closes exactly that row (same-ticker
  double-OPEN rows never mix levels/PnL again).
- Price misses are counted; past the threshold one Telegram alert fires
  (no spam), and recovery resets the counter.
- queue_actionable_signals isolates per-signal failures and reports counts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from bist_bot.db.database import Base, DatabaseManager, PaperTradeRecord
from bist_bot.db.repositories.portfolio_repository import PortfolioRepository
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.strategy.signal_models import SignalType


@pytest.fixture()
def repo(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "hardening.db"))
    repository = PortfolioRepository(manager=manager)
    Base.metadata.create_all(manager.engine) if hasattr(manager, "engine") else None
    yield repository
    if hasattr(manager, "engine"):
        manager.engine.dispose()


def _open_trade_id(repo_db, ticker, entry, sl, tp):
    with repo_db.manager.run_session(
        lambda session: session.scalars(
            sa.select(PaperTradeRecord).where(
                PaperTradeRecord.ticker == ticker,
                PaperTradeRecord.outcome == "OPEN",
            )
        ).all(),
        read_only=True,
    ) as trades:
        return [(t.id, t.signal_price) for t in trades]


def test_close_by_trade_id_targets_exact_row(tmp_path):
    """Ayni ticker'da iki OPEN satir: id ile kapatilan O satir, digeri OPEN kalir."""
    manager = DatabaseManager(sqlite_path=str(tmp_path / "byid.db"))
    repo = PortfolioRepository(manager=manager)
    repo.add_paper_trade("THYAO.IS", "🟢 AL", 100.0, stop_loss=95.0, target_price=110.0)
    repo.add_paper_trade("THYAO.IS", "🟢 AL", 105.0, stop_loss=100.0, target_price=115.0)

    open_rows = repo.get_open_paper_trades()
    assert len(open_rows) == 2
    older = min(open_rows, key=lambda t: t.id)  # entry 100
    newer = max(open_rows, key=lambda t: t.id)  # entry 105

    # Eski islemin stop seviyesine gore kapanis karari -> O id kapanmali.
    repo.close_paper_trade(
        "THYAO.IS", 94.0, "STOP_HIT", actual_profit_pct=-6.0, trade_id=older.id
    )

    remaining = repo.get_open_paper_trades()
    assert len(remaining) == 1
    assert remaining[0].id == newer.id

    from sqlalchemy.orm import Session

    with Session(manager.engine) as session:
        closed = session.get(PaperTradeRecord, older.id)
        assert closed.outcome == "CLOSED"
        assert closed.close_reason == "STOP_HIT"
        assert closed.actual_profit_pct == pytest.approx(-6.0)
    manager.engine.dispose()


def _skip_service(price_map, alerts, threshold=3):
    db = MagicMock()
    trade = SimpleNamespace(
        id=7, ticker="DEAD.IS", signal_type="🟢 AL", signal_price=100.0,
        stop_loss=95.0, target_price=110.0, direction="long",
    )
    db.get_open_paper_trades.return_value = [trade]
    fetcher = MagicMock()
    fetcher.fetch_all.return_value = price_map.get("fetch", {})
    cfg = SimpleNamespace(
        PAPER_MODE=True, PAPER_COOLDOWN_DAYS=0, PAPER_CLOSE_SKIP_WARN_THRESHOLD=threshold,
    )
    service = PaperTradeService(fetcher, db, settings=cfg, alerter=alerts.append)
    return service, db


def test_price_skip_alerts_once_after_threshold_and_resets():
    alerts: list[str] = []
    service, db = _skip_service({}, alerts, threshold=3)

    for _ in range(5):
        service.update_open_trades(signals=[])  # fiyat hic gelmiyor

    # Esik 3: 3. eksikte bir kez uyar, sonra spam yok.
    assert len(alerts) == 1
    assert "DEAD.IS" in alerts[0]
    db.close_paper_trade.assert_not_called()
    assert service._price_skip_counts["DEAD.IS"] == 5

    # Fiyat geri geldi: sayaç sıfırlanır, pozisyon normal akışa döner.
    alive = SimpleNamespace(
        ticker="DEAD.IS", price=96.0, signal_type=SignalType.BUY,
    )
    service.fetcher.fetch_all.return_value = {}
    db.get_open_paper_trades.return_value = [SimpleNamespace(
        id=7, ticker="DEAD.IS", signal_type="🟢 AL", signal_price=100.0,
        stop_loss=100.5, target_price=110.0, direction="long",
    )]
    service.update_open_trades(signals=[alive])
    assert "DEAD.IS" not in service._price_skip_counts


def test_queue_actionable_isolates_failures_and_reports():
    db = MagicMock()
    db.get_recent_closed_trades.return_value = []
    fetcher = MagicMock()
    cfg = SimpleNamespace(PAPER_MODE=True, PAPER_COOLDOWN_DAYS=0, DATA_INTERVAL="1d")

    good = SimpleNamespace(
        ticker="GOOD.IS", price=100.0, score=40,
        timestamp=datetime.now(UTC), stop_loss=95.0, target_price=110.0,
        signal_type=SignalType.BUY,
    )
    bad = SimpleNamespace(
        ticker="BAD.IS", price=100.0, score=40,
        timestamp=datetime.now(UTC), stop_loss=95.0, target_price=110.0,
        signal_type=SignalType.BUY,
    )

    call_count = {"n": 0}

    def fetch_single(ticker, period="3mo", **_):
        call_count["n"] += 1
        if ticker == "BAD.IS":
            raise RuntimeError("provider exploded")
        return None

    fetcher.fetch_single = fetch_single
    service = PaperTradeService(fetcher, db, settings=cfg)

    ok = service.queue_actionable_signals([good, bad])

    # Kötü hisse zinciri kırdı; iyi hisse yine de kuyruğa alındı.
    assert ok is False
    assert db.add_paper_trade.call_count == 1
    added = db.add_paper_trade.call_args.kwargs
    assert added["ticker"] == "GOOD.IS"
