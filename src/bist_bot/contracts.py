"""Shared protocol contracts for runtime integrations."""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from bist_bot.execution.base import (
    AccountInfo,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from bist_bot.strategy.signal_models import Signal


class DataFetcherProtocol(Protocol):
    def clear_cache(
        self,
        scope: str = ...,
        ticker: str | None = ...,
        period: str | None = ...,
        interval: str | None = ...,
    ) -> None: ...
    def fetch_all(
        self, period: str = ..., interval: str = ..., force: bool = ...
    ) -> dict[str, pd.DataFrame]: ...
    def fetch_single(
        self, ticker: str, period: str = ..., interval: str = ..., force: bool = ...
    ) -> pd.DataFrame | None: ...
    def fetch_multi_timeframe_all(
        self,
        trend_period: str = ...,
        trend_interval: str = ...,
        trigger_period: str = ...,
        trigger_interval: str = ...,
        force_refresh: bool = ...,
    ) -> dict[str, dict[str, pd.DataFrame]]: ...
    def fetch_multi_timeframe(
        self,
        tickers: list[str],
        trend_period: str = ...,
        trend_interval: str = ...,
        trigger_period: str = ...,
        trigger_interval: str = ...,
        force_refresh: bool = ...,
    ) -> dict[str, dict[str, pd.DataFrame]]: ...
    def get_cached_analysis(self, cache_key: str, force: bool = ...) -> Any | None: ...
    def store_analysis(self, cache_key: str, value: Any) -> None: ...


class StrategyEngineProtocol(Protocol):
    def scan_all(
        self, data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]]
    ) -> list[Signal]: ...
    def get_actionable_signals(self, signals: list[Signal]) -> list[Signal]: ...
    def analyze(
        self,
        ticker: str,
        df: pd.DataFrame | dict[str, pd.DataFrame],
        enforce_sector_limit: bool = ...,
    ) -> Signal | None: ...
    def get_last_rejection_breakdown(self) -> dict[str, Any]: ...


class NotifierProtocol(Protocol):
    def send_message(self, text: str, parse_mode: str = ...) -> bool: ...
    def send_signal(self, signal: Signal) -> bool: ...
    def send_scan_summary(self, signals: list[Signal], total_scanned: int) -> bool: ...
    def send_signal_change(self, ticker: str, old_signal: Signal, new_signal: Signal) -> bool: ...
    def send_startup_message(self) -> bool: ...


class SilentNotifier:
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        return True

    def send_signal(self, signal: Signal) -> bool:
        return True

    def send_scan_summary(self, signals: list[Signal], total_scanned: int) -> bool:
        return True

    def send_signal_change(self, ticker: str, old_signal: Signal, new_signal: Signal) -> bool:
        return True

    def send_startup_message(self) -> bool:
        return True


class SignalRepositoryProtocol(Protocol):
    def save_signal(self, signal: Signal) -> None: ...
    def save_signals(self, signals: list[Signal]) -> None: ...
    def save_scan_log(
        self,
        total: int,
        generated: int,
        buys: int,
        sells: int,
        actionable: int = 0,
        *,
        scan_id: str = ...,
        rejection_breakdown: dict[str, Any] | None = ...,
    ) -> None: ...
    def get_latest_signal(self, ticker: str) -> dict[str, Any] | None: ...
    def get_recent_signals(
        self, limit: int = ..., ticker: str | None = ...
    ) -> list[dict[str, Any]]: ...
    def get_performance_stats(self) -> dict[str, Any]: ...
    def get_latest_scan_log(self) -> dict[str, Any] | None: ...
    def get_recent_scan_logs(self, limit: int = ...) -> list[dict[str, Any]]: ...
    def save_latest_rejection_breakdown(self, payload: dict[str, Any]) -> None: ...
    def get_latest_rejection_breakdown(self) -> dict[str, Any]: ...
    def add_paper_trade(
        self,
        ticker: str,
        signal_type: str,
        signal_price: float,
        signal_time: Any = ...,
        score: int = ...,
        regime: str = ...,
    ) -> None: ...
    def get_open_paper_trades(self) -> list[Any]: ...
    def get_active_position_tickers(self) -> list[str]: ...
    def update_all_paper_close(self, prices: dict[str, float]) -> None: ...
    def create_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None = ...,
        state: str = ...,
        broker_order_id: str | None = ...,
        filled_qty: float = ...,
        avg_fill_price: float | None = ...,
    ) -> dict[str, Any]: ...
    def update_order(
        self,
        order_id: int,
        *,
        state: str | None = ...,
        broker_order_id: str | None = ...,
        filled_qty: float | None = ...,
        avg_fill_price: float | None = ...,
    ) -> dict[str, Any] | None: ...
    def get_pending_orders(self) -> list[dict[str, Any]]: ...
    def ping(self) -> bool: ...


class ExecutionProviderProtocol(Protocol):
    def authenticate(self) -> bool: ...
    def get_positions(self) -> list[Position]: ...
    def get_account_info(self) -> AccountInfo: ...
    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = ...,
        stop_price: float | None = ...,
    ) -> OrderResult: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_order_status(self, order_id: str) -> OrderStatus: ...
    def get_open_orders(self) -> list[Order]: ...
