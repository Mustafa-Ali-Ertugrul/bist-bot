from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import random
import re
import threading
import time
from typing import Any, Callable, Iterator, Optional, TypeVar

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    scoped_session,
    sessionmaker,
)
from sqlalchemy.pool import QueuePool

from bist_bot.config.settings import settings


class Base(DeclarativeBase):
    pass


def _validate_table_name(name: str) -> str:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError(
            f'Invalid SQL table name configured for PAPER_TRADES_TABLE: {name!r}'
        )
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
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reasons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    outcome_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    profit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class PaperTradeRecord(Base):
    __tablename__ = settings.PAPER_TRADES_TABLE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    signal_price: Mapped[float] = mapped_column(Float, nullable=False)
    signal_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filled_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")
    actual_profit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    close_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ScanLogRecord(Base):
    __tablename__ = "scan_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    total_scanned: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signals_generated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    buy_signals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sell_signals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


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
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


_T = TypeVar("_T")
_INIT_LOCK = threading.RLock()


class DatabaseManager:
    def __init__(
        self,
        database_url: Optional[str] = None,
        sqlite_path: Optional[str] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        busy_timeout_ms: int = 5000,
        write_retry_attempts: int = 3,
        write_retry_backoff_seconds: float = 0.05,
    ) -> None:
        self.database_url = (database_url or settings.DATABASE_URL or "").strip()
        self.sqlite_path = sqlite_path or settings.DB_PATH or '/tmp/bist_signals.db'
        self._is_sqlite = not self.database_url or self.database_url.startswith(
            "sqlite"
        )
        if self._is_sqlite:
            self._ensure_sqlite_parent_dir()
        self.busy_timeout_ms = busy_timeout_ms
        self.write_retry_attempts = max(int(write_retry_attempts), 1)
        self.write_retry_backoff_seconds = max(float(write_retry_backoff_seconds), 0.0)
        engine_url = self.database_url or f"sqlite:///{Path(self.sqlite_path)}"
        engine_kwargs: dict[str, Any] = {
            "future": True,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
            "pool_pre_ping": True,
        }
        if self._is_sqlite:
            engine_kwargs["poolclass"] = QueuePool
            engine_kwargs["connect_args"] = {
                "check_same_thread": False,
                "timeout": busy_timeout_ms / 1000,
            }
        self.engine = create_engine(engine_url, **engine_kwargs)
        if self._is_sqlite:
            self._register_pragmas()
        self.session_factory = scoped_session(
            sessionmaker(
                bind=self.engine, autoflush=False, expire_on_commit=False, future=True
            )
        )
        self._initialized = False
        self.initialize()

    def _ensure_sqlite_parent_dir(self) -> None:
        db_path = Path(self.sqlite_path)
        parent = db_path.parent
        if str(parent) in {"", "."}:
            return
        parent.mkdir(parents=True, exist_ok=True)

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
        with _INIT_LOCK:
            if self._initialized:
                return
            try:
                Base.metadata.create_all(self.engine)
            except OperationalError as exc:
                raise RuntimeError(
                    'Veri deposu başlatılamadı. DB_PATH veya DATABASE_URL yapılandırmasını kontrol edin.'
                ) from exc
            self._migrate_legacy_schema()
            self._seed_admin_user()
            self._initialized = True

    def _migrate_legacy_schema(self) -> None:
        if not self._is_sqlite:
            return
        paper_table = _validate_table_name(settings.PAPER_TRADES_TABLE)
        with self.engine.begin() as conn:
            signal_columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(signals)")).fetchall()
            }
            if "conditions" not in signal_columns:
                conn.execute(
                    text(
                        "ALTER TABLE signals ADD COLUMN conditions TEXT NOT NULL DEFAULT '[]'"
                    )
                )
            if "created_at" not in signal_columns:
                conn.execute(
                    text(
                        "ALTER TABLE signals ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"
                    )
                )
            if "position_size" not in signal_columns:
                conn.execute(
                    text("ALTER TABLE signals ADD COLUMN position_size INTEGER")
                )

            paper_columns = {
                row[1]
                for row in conn.execute(
                    text(f'PRAGMA table_info({paper_table})')
                ).fetchall()
            }
            if "stop_loss" not in paper_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {paper_table} ADD COLUMN stop_loss REAL"
                    )
                )
            if "target_price" not in paper_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {paper_table} ADD COLUMN target_price REAL"
                    )
                )
            if "exit_price" not in paper_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {paper_table} ADD COLUMN exit_price REAL"
                    )
                )
            if "exit_date" not in paper_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {paper_table} ADD COLUMN exit_date TEXT"
                    )
                )
            if "close_reason" not in paper_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {paper_table} ADD COLUMN close_reason TEXT"
                    )
                )
            if "close_time" not in paper_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {paper_table} ADD COLUMN close_time TEXT"
                    )
                )

            self._normalize_timestamp_columns(conn)

            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_signals_ticker_created_at ON signals(ticker, created_at DESC)"
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state)")
            )

    def _normalize_timestamp_columns(self, conn) -> None:
        """Convert legacy TEXT timestamps to ISO-8601 so SQLAlchemy DateTime can parse them.

        SQLite stores DateTime as TEXT in ISO format. Older rows may use
        non-ISO formats (e.g. ``YYYY-MM-DD HH:MM:SS``) or non-date values
        (e.g. ``STOP_HIT`` mistakenly stored in ``exit_date``). This migration
        normalizes them in-place.
        """
        paper_trades_table = _validate_table_name(settings.PAPER_TRADES_TABLE)
        migrations = {
            "signals": ["timestamp", "created_at", "outcome_date"],
            paper_trades_table: ["signal_time", "exit_date", "close_time"],
            "scan_log": ["timestamp"],
            "users": ["created_at", "updated_at"],
            "orders": ["created_at", "updated_at"],
            "app_settings": ["updated_at"],
        }
        for table, columns in migrations.items():
            try:
                col_info = {
                    row[1]: row[2]
                    for row in conn.execute(
                        text(f"PRAGMA table_info({table})")
                    ).fetchall()
                }
            except OperationalError:
                continue
            for col in columns:
                if col not in col_info:
                    continue
                conn.execute(
                    text(
                        f"UPDATE {table} SET {col} = "
                        f"CASE "
                        f"  WHEN {col} IS NULL OR {col} = '' THEN NULL "
                        f"  WHEN {col} GLOB '*[a-zA-Z]*' AND {col} NOT GLOB '*[0-9]*' THEN NULL "
                        f"  WHEN substr({col}, 11, 1) = ' ' THEN "
                        f"    substr({col}, 1, 10) || 'T' || substr({col}, 12) "
                        f"  ELSE {col} "
                        f"END "
                        f"WHERE {col} IS NOT NULL AND {col} != ''"
                    )
                )

    def _seed_admin_user(self) -> None:
        if not settings.admin_bootstrap_enabled:
            return

        now = self.now_utc()
        with self.engine.begin() as conn:
            has_users = conn.execute(
                text("SELECT id FROM users LIMIT 1")
            ).scalar_one_or_none()
            if has_users is not None:
                return
            try:
                conn.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO users (email, password_hash, role, created_at, updated_at)
                        VALUES (:email, :password_hash, 'admin', :created_at, :updated_at)
                        """
                    ),
                    {
                        "email": settings.ADMIN_BOOTSTRAP_EMAIL,
                        "password_hash": settings.ADMIN_BOOTSTRAP_PASSWORD_HASH,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            except IntegrityError:
                return

    @contextmanager
    def session_scope(self, *, read_only: bool = False) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            if not read_only:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self.session_factory.remove()

    def run_session(
        self,
        operation: Callable[[Session], _T],
        *,
        read_only: bool = False,
    ) -> _T:
        if read_only:
            with self.session_scope(read_only=True) as session:
                return operation(session)

        attempt = 0
        while True:
            try:
                with self.session_scope(read_only=False) as session:
                    return operation(session)
            except OperationalError as exc:
                if (
                    not self._is_locked_error(exc)
                    or attempt >= self.write_retry_attempts - 1
                ):
                    raise
                backoff = self.write_retry_backoff_seconds * (2**attempt)
                jitter = random.uniform(0, backoff * 0.5)
                time.sleep(backoff + jitter)
                attempt += 1

    def _is_locked_error(self, exc: OperationalError) -> bool:
        message = str(getattr(exc, "orig", exc)).lower()
        return "database is locked" in message or "database table is locked" in message

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def get_journal_mode(self) -> str:
        if not self._is_sqlite:
            return "n/a"
        with self.engine.connect() as conn:
            value = conn.execute(text("PRAGMA journal_mode")).scalar_one()
        return str(value)

    def now_utc(self) -> datetime:
        return datetime.now(UTC)

    def now_iso(self) -> str:
        return self.now_utc().isoformat(timespec="seconds")
