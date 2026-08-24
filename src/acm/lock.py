# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Non-blocking global write lock implementation for ACM (macOS/Linux)."""

import fcntl
import os
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Self

from acm.errors import SafetyBlockedError
from acm.util import get_lock_file, get_state_dir


class WriteLock:
    """Non-blocking global write lock context manager.

    Ensures only one ACM process performs mutating operations at a time.
    """

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = env
        self.lock_path: Path = get_lock_file(env)
        self._fd: int | None = None

    def acquire(self) -> None:
        """Acquire non-blocking exclusive file lock."""
        # Ensure state directory exists with 0700 permissions
        state_dir = get_state_dir(self.env)
        state_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(state_dir, 0o700)
        except OSError:
            pass

        self._fd = os.open(
            str(self.lock_path),
            os.O_RDWR | os.O_CREAT | os.O_TRUNC,
            0o600,
        )

        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as e:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            raise SafetyBlockedError(
                "⚠️ Another acm process is holding the write lock. Operation aborted."
            ) from e

    def release(self) -> None:
        """Release lock and close descriptor."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()
