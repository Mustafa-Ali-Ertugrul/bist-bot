"""Alembic environment for bist_bot schema migrations."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure src/ is importable when running `alembic` from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bist_bot.db.connection import resolve_database_url  # noqa: E402
from bist_bot.db.database import Base  # noqa: E402

config = context.config

if config.config_file_name is not None and not config.get_main_option("dont_mutate_root_logger"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _make_include_object(url: str):
    """Build the autogenerate filter bound to the target dialect.

    SQLite cannot reflect inline UNIQUE column definitions as named
    constraints, so any named UniqueConstraint in metadata trivially
    mismatches on SQLite (PostgreSQL reflects them properly, which is why
    the metadata naming convention exists). Skipping unique-constraint
    comparison on SQLite only keeps `alembic check` meaningful on both
    dialects; PostgreSQL remains the authoritative drift gate.
    """
    from sqlalchemy.engine import make_url

    try:
        dialect_name = make_url(url).get_dialect().name
    except Exception:
        dialect_name = ""

    def include_object(
        _object: object,
        _name: str | None,
        type_: str,
        _reflected: object,
        _compare_to: object | None,
    ) -> bool:
        return not (type_ == "unique_constraint" and dialect_name == "sqlite")

    return include_object


def get_url() -> str:
    """Resolve DB URL: prefer config option if set (e.g. tests), else runtime."""
    cfg_url = config.get_main_option("sqlalchemy.url")
    if cfg_url and cfg_url.strip():
        return cfg_url
    cfg = resolve_database_url()
    return cfg.url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_make_include_object(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_url()
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=_make_include_object(url),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
