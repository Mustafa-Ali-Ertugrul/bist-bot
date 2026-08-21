from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    scoped_session,
    sessionmaker,
)

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings

logger = get_logger(__name__, component="database")


class Base(DeclarativeBase):
    pass


def _validate_table_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        raise ValueError(f"Invalid SQL table name configured for PAPER_TRADES_TABLE: {name!r}")
    return name


def _quote_identifier(name: str) -> str:
    return f'"{_validate_table_name(name)}"'


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
    score_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaperTradeRecord(Base):
    __tablename__ = _validate_table_name(settings.PAPER_TRADES_TABLE)

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
    direction: Mapped[str] = mapped_column(String, nullable=True)
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
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False, default="ENTRY")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class LivePositionRecord(Base):
    __tablename__ = "live_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    side: Mapped[str] = mapped_column(String, nullable=False, default="LONG")
    entry_order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_size_method: Mapped[str | None] = mapped_column(String, nullable=True)
    exit_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees_paid: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    settlement_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="ENTRY_ORDERED", index=True)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    signal_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    regime: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class AuditRecord(Base):
    __tablename__ = "audit_trail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_state: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    trigger_source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


_T = TypeVar("_T")
_INIT_LOCK = threading.RLock()


class DatabaseManager:
    def __init__(
        self,
        database_url: str | None = None,
        sqlite_path: str | None = None,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_timeout: int | None = None,
        busy_timeout_ms: int | None = None,
        write_retry_attempts: int = 3,
        write_retry_backoff_seconds: float = 0.05,
    ) -> None:
        from bist_bot.db.connection import create_db_engine, resolve_database_url

        # Prefer explicit constructor args, else settings/env via connection resolver.
        settings_url = (getattr(settings, "DATABASE_URL", "") or "").strip()
        settings_path = getattr(settings, "DB_PATH", None) or "bist_signals.db"
        if database_url is None and sqlite_path is not None:
            # sqlite_path explicitly given, database_url not given → use sqlite_path
            cfg = resolve_database_url(database_url="", sqlite_path=sqlite_path)
        else:
            cfg = resolve_database_url(
                database_url=database_url if database_url is not None else settings_url,
                sqlite_path=sqlite_path if sqlite_path is not None else settings_path,
            )

        # Allow pool overrides from settings when not passed explicitly.
        if pool_size is None:
            pool_size = int(getattr(settings, "DB_POOL_SIZE", cfg.pool_size))
        if max_overflow is None:
            max_overflow = int(getattr(settings, "DB_MAX_OVERFLOW", cfg.max_overflow))
        if pool_timeout is None:
            pool_timeout = int(getattr(settings, "DB_POOL_TIMEOUT", cfg.pool_timeout))
        if busy_timeout_ms is None:
            busy_timeout_ms = int(getattr(settings, "DB_BUSY_TIMEOUT_MS", cfg.busy_timeout_ms))

        from dataclasses import replace as dc_replace

        cfg = dc_replace(
            cfg,
            pool_size=max(int(pool_size), 1),
            max_overflow=max(int(max_overflow), 0),
            pool_timeout=max(int(pool_timeout), 1),
            busy_timeout_ms=max(int(busy_timeout_ms), 0),
        )

        self.sqlite_path = cfg.sqlite_path or settings_path
        self.database_url = "" if cfg.is_sqlite else cfg.url
        self._is_sqlite = cfg.is_sqlite
        self._engine_config = cfg
        if self._is_sqlite:
            self._ensure_sqlite_parent_dir()
        self.busy_timeout_ms = cfg.busy_timeout_ms
        self.write_retry_attempts = max(int(write_retry_attempts), 1)
        self.write_retry_backoff_seconds = max(float(write_retry_backoff_seconds), 0.0)
        self.engine = create_db_engine(cfg)
        if self._is_sqlite:
            self._register_pragmas()
        self.session_factory = scoped_session(
            sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False, future=True)
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
                    "Veri deposu başlatılamadı. DB_PATH veya DATABASE_URL yapılandırmasını kontrol edin."
                ) from exc
            self._migrate_legacy_schema()
            self._seed_admin_user()
            self._warn_if_no_users()
            self._initialized = True

    def _warn_if_no_users(self) -> None:
        if not self._is_sqlite:
            return
        try:
            with self.engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
            if count == 0 and not settings.ALLOW_PUBLIC_REGISTRATION:
                logger.warning(
                    "no_users_and_registration_disabled",
                    message="Users table is empty and public registration is off. "
                    "Set ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD_HASH to seed an admin user.",
                )
        except OperationalError:
            pass
        except SQLAlchemyError:
            pass

    def _migrate_signals_table(self, conn) -> None:
        """Migrate signals table schema."""
        signal_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(signals)")).fetchall()
        }
        migrations = [
            ("conditions", "ALTER TABLE signals ADD COLUMN conditions TEXT NOT NULL DEFAULT '[]'"),
            ("created_at", "ALTER TABLE signals ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"),
            ("position_size", "ALTER TABLE signals ADD COLUMN position_size INTEGER"),
            ("expires_at", "ALTER TABLE signals ADD COLUMN expires_at TEXT"),
            ("score_breakdown", "ALTER TABLE signals ADD COLUMN score_breakdown TEXT"),
        ]
        for column, sql in migrations:
            if column not in signal_columns:
                conn.execute(text(sql))

    def _migrate_scan_log_table(self, conn) -> None:
        """Migrate scan_log table schema."""
        scan_log_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(scan_log)")).fetchall()
        }
        migrations = [
            ("scan_id", "ALTER TABLE scan_log ADD COLUMN scan_id TEXT"),
            ("rejection_breakdown", "ALTER TABLE scan_log ADD COLUMN rejection_breakdown TEXT"),
        ]
        for column, sql in migrations:
            if column not in scan_log_columns:
                conn.execute(text(sql))

    def _migrate_paper_trades_table(self, conn) -> None:
        """Migrate paper_trades table schema."""
        paper_table = _validate_table_name(settings.PAPER_TRADES_TABLE)
        quoted_paper_table = _quote_identifier(paper_table)
        paper_columns = {
            row[1]
            for row in conn.execute(text(f"PRAGMA table_info({quoted_paper_table})")).fetchall()
        }
        migrations = [
            ("stop_loss", f"ALTER TABLE {quoted_paper_table} ADD COLUMN stop_loss REAL"),
            ("target_price", f"ALTER TABLE {quoted_paper_table} ADD COLUMN target_price REAL"),
            ("exit_price", f"ALTER TABLE {quoted_paper_table} ADD COLUMN exit_price REAL"),
            ("exit_date", f"ALTER TABLE {quoted_paper_table} ADD COLUMN exit_date TEXT"),
            ("close_reason", f"ALTER TABLE {quoted_paper_table} ADD COLUMN close_reason TEXT"),
            ("close_time", f"ALTER TABLE {quoted_paper_table} ADD COLUMN close_time TEXT"),
            ("direction", f"ALTER TABLE {quoted_paper_table} ADD COLUMN direction TEXT"),
        ]
        for column, sql in migrations:
            if column not in paper_columns:
                conn.execute(text(sql))

    def _create_indexes(self, conn) -> None:
        """Create database indexes."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_signals_ticker_created_at ON signals(ticker, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state)",
            "CREATE INDEX IF NOT EXISTS idx_scan_log_scan_id ON scan_log(scan_id)",
        ]
        for sql in indexes:
            conn.execute(text(sql))

    def _migrate_agent_schema(self, conn) -> None:
        """Migrate agent-related tables and order columns."""
        order_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(orders)")).fetchall()
        }
        order_migrations = [
            ("position_id", "ALTER TABLE orders ADD COLUMN position_id INTEGER"),
            ("purpose", "ALTER TABLE orders ADD COLUMN purpose TEXT NOT NULL DEFAULT 'ENTRY'"),
            ("metadata_json", "ALTER TABLE orders ADD COLUMN metadata_json TEXT"),
        ]
        for column, sql in order_migrations:
            if column not in order_columns:
                conn.execute(text(sql))
        agent_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_live_positions_state ON live_positions(state)",
            "CREATE INDEX IF NOT EXISTS idx_live_positions_ticker ON live_positions(ticker)",
            "CREATE INDEX IF NOT EXISTS idx_audit_trail_event_type ON audit_trail(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp ON audit_trail(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_orders_position_id ON orders(position_id)",
        ]
        for sql in agent_indexes:
            conn.execute(text(sql))

    def _migrate_legacy_schema(self) -> None:
        if not self._is_sqlite:
            return
        with self.engine.begin() as conn:
            self._migrate_signals_table(conn)
            self._migrate_scan_log_table(conn)
            self._migrate_paper_trades_table(conn)
            self._normalize_timestamp_columns(conn)
            self._migrate_agent_schema(conn)
            self._create_indexes(conn)

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
            quoted_table = _quote_identifier(table)
            try:
                col_info = {
                    row[1]: row[2]
                    for row in conn.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
                }
            except OperationalError:
                continue
            for col in columns:
                if col not in col_info:
                    continue
                quoted_col = _quote_identifier(col)
                conn.execute(
                    text(
                        f"UPDATE {quoted_table} SET {quoted_col} = "
                        f"CASE "
                        f"  WHEN {quoted_col} IS NULL OR {quoted_col} = '' THEN NULL "
                        f"  WHEN {quoted_col} GLOB '*[a-zA-Z]*' "
                        f"AND {quoted_col} NOT GLOB '*[0-9]*' THEN NULL "
                        f"  WHEN substr({quoted_col}, 11, 1) = ' ' THEN "
                        f"    substr({quoted_col}, 1, 10) || 'T' || substr({quoted_col}, 12) "
                        f"  ELSE {quoted_col} "
                        f"END "
                        f"WHERE {quoted_col} IS NOT NULL AND {quoted_col} != ''"
                    )
                )

    def _seed_admin_user(self) -> None:
        if not settings.admin_bootstrap_enabled:
            logger.info(
                "admin_bootstrap_skipped",
                reason="ADMIN_BOOTSTRAP_EMAIL or ADMIN_BOOTSTRAP_PASSWORD_HASH not set",
            )
            return

        logger.info(
            "admin_bootstrap_start",
            email=settings.ADMIN_BOOTSTRAP_EMAIL,
        )

        now = self.now_utc()
        with self.engine.begin() as conn:
            admin_exists = conn.execute(
                text("SELECT id FROM users WHERE email = :email LIMIT 1"),
                {"email": settings.ADMIN_BOOTSTRAP_EMAIL},
            ).scalar_one_or_none()
            if admin_exists is not None:
                if settings.ADMIN_BOOTSTRAP_UPDATE_EXISTING:
                    logger.info(
                        "admin_bootstrap_existing_admin_found",
                        email=settings.ADMIN_BOOTSTRAP_EMAIL,
                    )
                    conn.execute(
                        text(
                            "UPDATE users SET password_hash = :password_hash, updated_at = :updated_at WHERE email = :email"
                        ),
                        {
                            "email": settings.ADMIN_BOOTSTRAP_EMAIL,
                            "password_hash": settings.ADMIN_BOOTSTRAP_PASSWORD_HASH,
                            "updated_at": now,
                        },
                    )
                    logger.info(
                        "admin_bootstrap_existing_admin_updated",
                        email=settings.ADMIN_BOOTSTRAP_EMAIL,
                    )
                else:
                    logger.info(
                        "admin_bootstrap_existing_admin_update_skipped",
                        reason="admin_exists",
                        email=settings.ADMIN_BOOTSTRAP_EMAIL,
                    )
                return
            try:
                conn.execute(
                    text(
                        # Plain INSERT for cross-dialect compatibility (SQLite +
                        # PostgreSQL). The email existence check above plus the
                        # IntegrityError handler below cover the duplicate case.
                        """
                        INSERT INTO users (email, password_hash, role, created_at, updated_at)
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
                logger.info(
                    "admin_bootstrap_created",
                    email=settings.ADMIN_BOOTSTRAP_EMAIL,
                )
            except IntegrityError:
                logger.warning(
                    "admin_bootstrap_duplicate",
                    email=settings.ADMIN_BOOTSTRAP_EMAIL,
                )
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
                if not self._is_locked_error(exc) or attempt >= self.write_retry_attempts - 1:
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
        except OperationalError:
            return False
        except SQLAlchemyError:
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
