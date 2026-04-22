from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import Float, Integer, String, Text, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

from bist_bot.config.settings import settings


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
    position_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reasons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    outcome_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PaperTradeRecord(Base):
    __tablename__ = settings.PAPER_TRADES_TABLE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    signal_price: Mapped[float] = mapped_column(Float, nullable=False)
    signal_time: Mapped[str] = mapped_column(Text, nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filled_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")
    actual_profit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    close_time: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ScanLogRecord(Base):
    __tablename__ = "scan_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    total_scanned: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signals_generated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    buy_signals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sell_signals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ConfigRecord(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="admin")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class OrderRecord(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    side: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class DatabaseManager:
    def __init__(
        self,
        sqlite_path: Optional[str] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.sqlite_path = sqlite_path or settings.DB_PATH
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
        self._seed_admin_user()

    def _migrate_legacy_schema(self) -> None:
        with self.engine.begin() as conn:
            signal_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(signals)")).fetchall()}
            if "conditions" not in signal_columns:
                conn.execute(text("ALTER TABLE signals ADD COLUMN conditions TEXT NOT NULL DEFAULT '[]'"))
            if "created_at" not in signal_columns:
                conn.execute(text("ALTER TABLE signals ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"))
            if "position_size" not in signal_columns:
                conn.execute(text("ALTER TABLE signals ADD COLUMN position_size INTEGER"))

            paper_columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({settings.PAPER_TRADES_TABLE})")).fetchall()}
            if "stop_loss" not in paper_columns:
                conn.execute(text(f"ALTER TABLE {settings.PAPER_TRADES_TABLE} ADD COLUMN stop_loss REAL"))
            if "target_price" not in paper_columns:
                conn.execute(text(f"ALTER TABLE {settings.PAPER_TRADES_TABLE} ADD COLUMN target_price REAL"))
            if "exit_price" not in paper_columns:
                conn.execute(text(f"ALTER TABLE {settings.PAPER_TRADES_TABLE} ADD COLUMN exit_price REAL"))
            if "exit_date" not in paper_columns:
                conn.execute(text(f"ALTER TABLE {settings.PAPER_TRADES_TABLE} ADD COLUMN exit_date TEXT"))
            if "close_reason" not in paper_columns:
                conn.execute(text(f"ALTER TABLE {settings.PAPER_TRADES_TABLE} ADD COLUMN close_reason TEXT"))
            if "close_time" not in paper_columns:
                conn.execute(text(f"ALTER TABLE {settings.PAPER_TRADES_TABLE} ADD COLUMN close_time TEXT"))

            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_signals_ticker_created_at ON signals(ticker, created_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state)"))

    def _seed_admin_user(self) -> None:
        if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD_HASH:
            return

        now = self.now_iso()
        with self.engine.begin() as conn:
            has_users = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar_one_or_none()
            if has_users is not None:
                return

            conn.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, role, created_at, updated_at)
                    VALUES (:email, :password_hash, 'admin', :created_at, :updated_at)
                    """
                ),
                {
                    "email": settings.ADMIN_EMAIL,
                    "password_hash": settings.ADMIN_PASSWORD_HASH,
                    "created_at": now,
                    "updated_at": now,
                },
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
        return datetime.now(UTC).isoformat(timespec="seconds")
