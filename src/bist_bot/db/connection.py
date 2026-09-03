"""Database engine factory and URL resolution for SQLite / PostgreSQL.

This module centralizes connection pooling policy:

- SQLite: ``NullPool`` + ``check_same_thread=False`` (WAL enabled by DatabaseManager)
- PostgreSQL: ``pool_size`` / ``max_overflow`` / ``pool_timeout`` + ``pool_pre_ping``

Environment:
- ``DATABASE_URL`` or ``BIST_BOT_DATABASE_URL``
- ``DB_PATH`` for local SQLite file fallback
- ``DB_POOL_SIZE``, ``DB_MAX_OVERFLOW``, ``DB_POOL_TIMEOUT``
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from bist_bot.app_logging import get_logger

logger = get_logger(__name__, component="database")


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        # Accept BIST_BOT_ prefix aliases
        alias = os.environ.get(f"BIST_BOT_{name}")
        if alias is None or not str(alias).strip():
            return default
        return str(alias).strip()
    return str(value).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _postgres_driver_available() -> bool:
    """Return True when the ``psycopg2`` DBAPI required by postgres URLs is importable."""
    try:
        return importlib.util.find_spec("psycopg2") is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


@dataclass(frozen=True)
class EngineConfig:
    url: str
    is_sqlite: bool
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    busy_timeout_ms: int = 200
    sqlite_path: str | None = None


def resolve_database_url(
    database_url: str | None = None,
    sqlite_path: str | None = None,
) -> EngineConfig:
    """Resolve the effective SQLAlchemy URL and backend kind.

    Semantics:
    - If ``database_url`` is explicitly provided (including empty string), env is
      not consulted for the URL. Empty string forces SQLite via ``sqlite_path``.
    - If ``database_url`` is ``None``, read ``DATABASE_URL`` / ``BIST_BOT_DATABASE_URL``.
    """
    if database_url is not None:
        url = database_url.strip()
    else:
        url = _env("DATABASE_URL", "")

    path = (sqlite_path or "").strip() or _env("DB_PATH", "bist_signals.db")

    if not url:
        abs_path = Path(path).expanduser()
        url = f"sqlite:///{abs_path.as_posix()}"

    # Normalize bare postgresql:// to use psycopg2 driver if no dialect driver given.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]

    is_sqlite = url.startswith("sqlite:")
    if not is_sqlite and not _postgres_driver_available():
        # Postgres URL configured but its DBAPI is missing: warn loudly, run on SQLite.
        logger.warning(
            "postgres_driver_missing_sqlite_fallback",
            message="DATABASE_URL points to PostgreSQL but the psycopg2 driver is not "
            "installed. Falling back to local SQLite (DB_PATH). Install psycopg2-binary "
            "to use PostgreSQL, or unset DATABASE_URL to silence this warning.",
            db_path=path,
        )
        abs_path = Path(path).expanduser()
        url = f"sqlite:///{abs_path.as_posix()}"
        is_sqlite = True
    pool_size = _env_int("DB_POOL_SIZE", 10)
    max_overflow = _env_int("DB_MAX_OVERFLOW", 20)
    pool_timeout = _env_int("DB_POOL_TIMEOUT", 30)
    busy_timeout_ms = _env_int("DB_BUSY_TIMEOUT_MS", 200)

    return EngineConfig(
        url=url,
        is_sqlite=is_sqlite,
        pool_size=max(pool_size, 1),
        max_overflow=max(max_overflow, 0),
        pool_timeout=max(pool_timeout, 1),
        busy_timeout_ms=max(busy_timeout_ms, 0),
        sqlite_path=path if is_sqlite else None,
    )


def is_postgres_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme.startswith("postgresql") or parsed.scheme.startswith("postgres")


def create_db_engine(config: EngineConfig | None = None, **overrides: Any) -> Engine:
    """Create a SQLAlchemy engine with backend-appropriate pooling."""
    cfg = config or resolve_database_url()
    engine_kwargs: dict[str, Any] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if cfg.is_sqlite:
        from sqlalchemy.pool import NullPool

        engine_kwargs["poolclass"] = NullPool
        engine_kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": cfg.busy_timeout_ms / 1000.0,
        }
    else:
        engine_kwargs["pool_size"] = cfg.pool_size
        engine_kwargs["max_overflow"] = cfg.max_overflow
        engine_kwargs["pool_timeout"] = cfg.pool_timeout

    engine_kwargs.update(overrides)
    return create_engine(cfg.url, **engine_kwargs)


__all__ = [
    "EngineConfig",
    "create_db_engine",
    "is_postgres_url",
    "resolve_database_url",
]
