"""Sprint 2 — unified trade ledger (paper + shadow dual-write) tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bist_bot.config.settings import settings
from bist_bot.db.database import Base, DatabaseManager
from bist_bot.db.repositories import AppRepository
from bist_bot.db.repositories.ledger_repository import (
    KIND_PAPER,
    KIND_SHADOW,
    STATUS_CLOSED,
    STATUS_OPEN,
)
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.services.shadow_trade_service import ShadowTradeService
from bist_bot.strategy.signal_models import Signal, SignalType

ENTRY_TIME = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


class _StubFetcher:
    """No market data — regime is patched at the service level in tests."""

    def fetch_single(self, ticker, period="3mo"):
        return None


class _LedgerBoomRepo:
    """Facade wrapper whose ledger methods raise — isolation contract.

    B3: unified-ledger failures must never break paper/shadow flows.
    """

    def __init__(self, repository: AppRepository) -> None:
        self._repository = repository

    def __getattr__(self, name: str):
        if name in ("record_ledger_open", "record_ledger_close"):
            raise RuntimeError("ledger down")
        return getattr(self._repository, name)


def _signal(
    ticker: str = "THYAO.IS",
    *,
    score: float = 22.0,
    signal_type: SignalType = SignalType.RADAR,
    price: float = 100.0,
) -> Signal:
    return Signal(
        ticker=ticker,
        signal_type=signal_type,
        score=score,
        price=price,
        stop_loss=95.0,
        target_price=110.0,
        agreement_ratio=0.5,
        reasons=["momentum", "volume"],
        timestamp=ENTRY_TIME,
        buy_threshold=25.0,
    )


@pytest.fixture()
def manager(tmp_path):
    db_manager = DatabaseManager(sqlite_path=str(tmp_path / "ledger.db"))
    Base.metadata.create_all(db_manager.engine)
    yield db_manager
    db_manager.engine.dispose()


@pytest.fixture()
def app_repo(manager):
    return AppRepository(manager=manager)


# ---------------------------------------------------------------- repository


def test_repository_roundtrip(app_repo):
    ledger_id = app_repo.record_ledger_open(
        kind=KIND_PAPER,
        ticker="THYAO.IS",
        signal_type="RADAR",
        direction="long",
        score=27.0,
        regime="UPTREND",
        entry_price=100.0,
        entry_time=ENTRY_TIME,
        stop_loss=95.0,
        target_price=110.0,
        paper_trade_id=7,
    )
    assert isinstance(ledger_id, int)

    open_rows = app_repo.get_ledger_open(kind=KIND_PAPER)
    assert len(open_rows) == 1
    assert open_rows[0].paper_trade_id == 7
    assert open_rows[0].status == STATUS_OPEN
    assert open_rows[0].regime == "UPTREND"

    closed = app_repo.record_ledger_close(
        KIND_PAPER,
        paper_trade_id=7,
        exit_price=110.0,
        close_reason="TARGET_HIT",
        gross_pnl_pct=10.0,
        net_pnl_pct=9.4,
    )
    assert closed is True
    assert app_repo.get_ledger_open(kind=KIND_PAPER) == []

    closed_rows = app_repo.get_ledger_closed(kind=KIND_PAPER)
    assert len(closed_rows) == 1
    assert closed_rows[0].status == STATUS_CLOSED
    assert closed_rows[0].close_reason == "TARGET_HIT"
    assert closed_rows[0].gross_pnl_pct == pytest.approx(10.0)
    assert closed_rows[0].net_pnl_pct == pytest.approx(9.4)


def test_close_entry_requires_identifier(app_repo):
    with pytest.raises(ValueError, match="ticker or paper_trade_id"):
        app_repo.record_ledger_close(KIND_PAPER, exit_price=100.0)


def test_kind_filter_isolates_ledgers(app_repo):
    app_repo.record_ledger_open(
        kind=KIND_PAPER,
        ticker="THYAO.IS",
        signal_type="RADAR",
        entry_price=100.0,
    )
    app_repo.record_ledger_open(
        kind=KIND_SHADOW,
        ticker="TAVHL.IS",
        signal_type="RADAR",
        entry_price=50.0,
    )
    assert len(app_repo.get_ledger_open(kind=KIND_PAPER)) == 1
    assert len(app_repo.get_ledger_open(kind=KIND_SHADOW)) == 1
    assert len(app_repo.get_ledger_open()) == 2


# ------------------------------------------------------------- paper flow


def test_paper_service_dual_write(app_repo):
    service = PaperTradeService(
        _StubFetcher(),
        app_repo,
        settings=settings.replace(PAPER_MODE=True),
    )
    signal = _signal(score=27.0)
    with patch(
        "bist_bot.services.paper_trade_service.detect_regime",
        lambda _df: SimpleNamespace(value="TRENDING"),
    ):
        assert service.queue_actionable_signals([signal]) is True

    # Paper trade eklendi, ledger'a 1:1 mirror eklendi.
    paper_trades = app_repo.get_open_paper_trades()
    assert len(paper_trades) == 1
    open_rows = app_repo.get_ledger_open(kind=KIND_PAPER)
    assert len(open_rows) == 1
    assert open_rows[0].ticker == "THYAO.IS"
    assert open_rows[0].paper_trade_id == paper_trades[0].id
    assert open_rows[0].regime == "TRENDING"
    assert open_rows[0].score == pytest.approx(27.0)

    service._close_trade(paper_trades[0], 110.0, "TARGET_HIT", "long")

    closed_rows = app_repo.get_ledger_closed(kind=KIND_PAPER)
    assert len(closed_rows) == 1
    assert closed_rows[0].close_reason == "TARGET_HIT"
    assert closed_rows[0].exit_price == pytest.approx(110.0)
    # Gross = komisyonsuz %10; net = komisyon düşülmüş hali (ayrık kolonlar).
    assert closed_rows[0].gross_pnl_pct == pytest.approx(10.0)
    assert 0 < closed_rows[0].net_pnl_pct < 10.0


def test_paper_flow_survives_ledger_outage(app_repo):
    boom_repo = _LedgerBoomRepo(app_repo)
    service = PaperTradeService(
        _StubFetcher(),
        boom_repo,
        settings=settings.replace(PAPER_MODE=True),
    )
    signal = _signal(score=27.0)
    with patch(
        "bist_bot.services.paper_trade_service.detect_regime",
        lambda _df: SimpleNamespace(value="TRENDING"),
    ):
        assert service.queue_actionable_signals([signal]) is True

    # B3: ledger patlasa da paper trade kaydı tamamlanır.
    assert len(app_repo.get_open_paper_trades()) == 1
    assert app_repo.get_ledger_open(kind=KIND_PAPER) == []


def test_paper_service_without_ledger_facade(app_repo):
    """Backward compat: facade'sız (eski) db sözleşmesi sessizce atlanır.

    Eski test mock'ları yalnızca ``add_paper_trade`` sunar; bu durumda
    açılış/yakınma ledger'a hiç yazılmaz ama akış çalışmaya devam eder.
    """

    class _BareDb:
        def __init__(self, repository: AppRepository) -> None:
            self._add_paper_trade = repository.add_paper_trade

        def add_paper_trade(self, *args, **kwargs):
            return self._add_paper_trade(*args, **kwargs)

    service = PaperTradeService(
        _StubFetcher(), _BareDb(app_repo), settings=settings.replace(PAPER_MODE=True)
    )
    signal = _signal(score=27.0)
    with patch(
        "bist_bot.services.paper_trade_service.detect_regime",
        lambda _df: SimpleNamespace(value="TRENDING"),
    ):
        assert service.queue_actionable_signals([signal]) is True
    assert len(app_repo.get_open_paper_trades()) == 1
    assert app_repo.get_ledger_open(kind=KIND_PAPER) == []


# ------------------------------------------------------------ shadow flow


def _shadow_service(app_repo, tmp_path) -> ShadowTradeService:
    return ShadowTradeService(
        settings=settings.replace(
            SHADOW_ENABLED=True,
            SHADOW_HOLDING_DAYS=5,
            SHADOW_ONLY_ROBUST=False,
            SHADOW_MIN_SCORE=15,
        ),
        results_dir=tmp_path,
        robust_tickers=set(),
        db=app_repo,
    )


def test_shadow_service_dual_write(app_repo, tmp_path):
    service = _shadow_service(app_repo, tmp_path)
    signal = _signal(score=22.0)

    service.process_scan([signal], now=ENTRY_TIME)

    open_rows = app_repo.get_ledger_open(kind=KIND_SHADOW)
    assert len(open_rows) == 1
    assert open_rows[0].ticker == "THYAO.IS"
    assert open_rows[0].direction == "long"
    assert open_rows[0].entry_price == pytest.approx(100.0)
    assert open_rows[0].agreement_ratio == pytest.approx(0.5)
    assert open_rows[0].stop_loss == pytest.approx(95.0)

    # 6 gün sonra: holding süresi doldu -> timeout kapanışı + ledger mirror.
    service.process_scan([signal], now=ENTRY_TIME + timedelta(days=6))

    closed_rows = app_repo.get_ledger_closed(kind=KIND_SHADOW)
    assert len(closed_rows) == 1
    assert closed_rows[0].close_reason == "timeout"
    assert closed_rows[0].gross_pnl_pct == pytest.approx(0.0)
    # Gölge PnL komisyonsuzdur — net kolonu boş kalır.
    assert closed_rows[0].net_pnl_pct is None


def test_shadow_dual_write_without_db(tmp_path):
    """db=None (eski davranış) dosya tabanlı akışı bozmaz."""
    service = ShadowTradeService(
        settings=settings.replace(
            SHADOW_ENABLED=True,
            SHADOW_HOLDING_DAYS=5,
            SHADOW_ONLY_ROBUST=False,
            SHADOW_MIN_SCORE=15,
        ),
        results_dir=tmp_path,
        robust_tickers=set(),
    )
    signal = _signal(score=22.0)
    closed_first = service.process_scan([signal], now=ENTRY_TIME)
    assert closed_first == []
    closed_second = service.process_scan([signal], now=ENTRY_TIME + timedelta(days=6))
    assert len(closed_second) == 1
    assert closed_second[0]["hit"] == "timeout"
