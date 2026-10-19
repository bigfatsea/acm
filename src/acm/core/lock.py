"""Non-blocking global write lock (macOS/Linux, ``fcntl.flock``)."""

import contextlib
import fcntl
import os
from types import TracebackType
from typing import Self

from acm.core.context import Ctx
from acm.core.errors import SafetyBlockedError


class WriteLock:
    """Ensures a single ACM process performs mutating operations at a time."""

    def __init__(self, ctx: Ctx) -> None:
        self._ctx = ctx
        self._fd: int | None = None

    def acquire(self) -> None:
        state_dir = self._ctx.state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(state_dir, 0o700)
        fd = os.open(str(self._ctx.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            raise SafetyBlockedError(
                "another acm process is holding the write lock; operation aborted"
            ) from e
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
