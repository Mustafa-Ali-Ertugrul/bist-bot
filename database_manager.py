from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import Float, Integer, String, Text, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

import config


class Base(DeclarativeBase):
    pass


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reasons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    outcome_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PaperTradeRecord(Base):
    __tablename__ = config.PAPER_TRADES_TABLE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    signal_price: Mapped[float] = mapped_column(Float, nullable=False)
    signal_time: Mapped[str] = mapped_column(Text, nullable=False)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filled_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")
    actual_profit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ScanLogRecord(Base):
    __tablename__ = "scan_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    total_scanned: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signals_generated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    buy_signals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sell_signals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class DatabaseManager:
    def __init__(
        self,
        sqlite_path: Optional[str] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.sqlite_path = sqlite_path or config.DB_PATH
        self.busy_timeout_ms = busy_timeout_ms
        self.engine = create_engine(
            f"sqlite:///{Path(self.sqlite_path)}",
            future=True,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            connect_args={
                "check_same_thread": False,
                "timeout": busy_timeout_ms / 1000,
            },
        )
        self._register_pragmas()
        self.session_factory = scoped_session(
            sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False, future=True)
        )
        self.initialize()

    def _register_pragmas(self) -> None:
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        self._migrate_legacy_schema()

    def _migrate_legacy_schema(self) -> None:
        with self.engine.begin() as conn:
            signal_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(signals)")).fetchall()
            }
            if "conditions" not in signal_columns:
                conn.execute(text("ALTER TABLE signals ADD COLUMN conditions TEXT NOT NULL DEFAULT '[]'"))
            if "created_at" not in signal_columns:
                conn.execute(text("ALTER TABLE signals ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"))

            paper_trade_columns = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({config.PAPER_TRADES_TABLE})")).fetchall()
            }
            if "exit_price" not in paper_trade_columns:
                conn.execute(text(f"ALTER TABLE {config.PAPER_TRADES_TABLE} ADD COLUMN exit_price REAL"))
            if "exit_date" not in paper_trade_columns:
                conn.execute(text(f"ALTER TABLE {config.PAPER_TRADES_TABLE} ADD COLUMN exit_date TEXT"))

            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_signals_created_at "
                    "ON signals(created_at DESC)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_signals_ticker_created_at "
                    "ON signals(ticker, created_at DESC)"
                )
            )

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self.session_factory.remove()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def get_journal_mode(self) -> str:
        with self.engine.connect() as conn:
            value = conn.execute(text("PRAGMA journal_mode")).scalar_one()
        return str(value)

    def now_iso(self) -> str:
        return datetime.utcnow().isoformat(timespec="seconds")
