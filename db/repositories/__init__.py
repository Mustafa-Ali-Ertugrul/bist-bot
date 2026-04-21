"""Repository facade used by application runtime code."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from db.database import DatabaseManager
from db.repositories.config_repository import ConfigRepository
from db.repositories.portfolio_repository import PortfolioRepository
from db.repositories.signals_repository import SignalsRepository
from signal_models import Signal


class AppRepository:
    """Thin application-facing facade over signal, portfolio, and config repositories."""

    def __init__(self, manager: Optional[DatabaseManager] = None) -> None:
        self.manager = manager or DatabaseManager()
        self.signals = SignalsRepository(self.manager)
        self.portfolio = PortfolioRepository(self.manager)
        self.config = ConfigRepository(self.manager)

    def ping(self) -> bool:
        return self.manager.ping()

    def save_signal(self, signal: Signal) -> None:
        return self.signals.save_signal(signal)

    def save_signals(self, signals: Sequence[Signal]) -> None:
        for signal in signals:
            self.save_signal(signal)

    def get_signals(self, limit: int = 50, ticker: str | None = None):
        return self.signals.get_signals(limit=limit, ticker=ticker)

    def get_recent_signals(self, limit: int = 50, ticker: str | None = None):
        return self.signals.get_recent_signals(limit=limit, ticker=ticker)

    def signal_exists(self, ticker: str, signal_type: str | None = None) -> bool:
        return self.signals.signal_exists(ticker, signal_type=signal_type)

    def get_latest_signal(self, ticker: str):
        return self.signals.get_latest_signal(ticker)

    def save_scan_log(self, total: int, generated: int, buys: int, sells: int):
        return self.signals.save_scan_log(total, generated, buys, sells)

    def update_outcome(self, signal_id: int, outcome: str, outcome_price: float):
        return self.signals.update_outcome(signal_id, outcome, outcome_price)

    def get_performance_stats(self):
        return self.signals.get_performance_stats()

    def add_paper_trade(self, *args, **kwargs):
        return self.portfolio.add_paper_trade(*args, **kwargs)

    def update_paper_close(self, *args, **kwargs):
        return self.portfolio.update_paper_close(*args, **kwargs)

    def update_all_paper_close(self, *args, **kwargs):
        return self.portfolio.update_all_paper_close(*args, **kwargs)

    def get_open_paper_trades(self):
        return self.portfolio.get_open_paper_trades()

    def close_paper_trade(self, *args, **kwargs):
        return self.portfolio.close_paper_trade(*args, **kwargs)

    def get_paper_performance(self):
        return self.portfolio.get_paper_performance()
