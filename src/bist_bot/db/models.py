"""SQLAlchemy ORM models for the bist-bot database schema."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bist_bot.config.settings import settings


class Base(DeclarativeBase):
    pass


def _validate_table_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Invalid SQL table name configured for PAPER_TRADES_TABLE: {name!r}")
    return name


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    reasons: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    outcome_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PaperTradeRecord(Base):
    __tablename__ = settings.PAPER_TRADES_TABLE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    signal_price: Mapped[float] = mapped_column(Float, nullable=False)
    signal_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regime: Mapped[str | None] = mapped_column(String, nullable=True)
    filled_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")
    actual_profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ScanLogRecord(Base):
    __tablename__ = "scan_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    total_scanned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signals_generated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_signals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sell_signals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actionable: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    rejection_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfigRecord(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class OrderRecord(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    side: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)


__all__ = [
    "Base",
    "ConfigRecord",
    "OrderRecord",
    "PaperTradeRecord",
    "ScanLogRecord",
    "SignalRecord",
    "UserRecord",
    "_validate_table_name",
]