"""Cross-platform advisory file lock enforcing single-writer scan execution."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import TextIO

try:  # pragma: no cover - platform branch
    import fcntl  # POSIX (Linux/macOS)
except ImportError:  # pragma: no cover - platform branch
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - platform branch
    import msvcrt  # Windows
except ImportError:  # pragma: no cover - platform branch
    msvcrt = None  # type: ignore[assignment]

DEFAULT_LOCK_PATH = str(Path(tempfile.gettempdir()) / "bist_bot_scan.lock")
_POLL_INTERVAL_SECONDS = 0.05


class ScanLock:
    """Advisory exclusive lock guarding scan entry across threads and processes.

    Uses ``flock(2)`` on POSIX and ``msvcrt.locking`` on Windows so the same
    lock path serializes scans from the scheduler, CLI, HTTP API, and the
    Streamlit runtime regardless of platform.
    """

    def __init__(self, lock_path: str | None = None) -> None:
        self.lock_path = lock_path or DEFAULT_LOCK_PATH
        self._file: TextIO | None = None

    def acquire(self, timeout: float = 0.0) -> bool:
        """Acquire the lock, polling up to ``timeout`` seconds; no wait when 0."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                opened = open(self.lock_path, "w")  # noqa: SIM115 - lock handle stays open
            except OSError:
                return False
            if self._try_lock(opened):
                self._file = opened
                return True
            try:
                opened.close()
            except OSError:  # Windows: flush of unwritable buffer on close
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_INTERVAL_SECONDS)

    def _try_lock(self, file: TextIO) -> bool:
        if fcntl is not None:
            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False
        if msvcrt is not None:
            try:
                file.write("x")
                file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        return False

    def release(self) -> None:
        """Release the lock and close the underlying file handle."""
        if self._file is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> ScanLock:
        if not self.acquire(timeout=0.0):
            raise RuntimeError("Another scan is already running")
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()