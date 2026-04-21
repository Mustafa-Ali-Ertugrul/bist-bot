"""Centralized logging setup for CLI entry points."""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler


def configure_logging(
    *,
    level: int = logging.INFO,
    log_file: str | None = "bot.log",
    fmt: str = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt: str = "%H:%M:%S",
) -> None:
    """Configure root logging for application entry points."""
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    formatter = logging.Formatter(fmt, datefmt=datefmt)
    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)
