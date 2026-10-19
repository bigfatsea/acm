"""Atomic, link- and permission-preserving file writes."""

import contextlib
import hashlib
import os
import stat
from pathlib import Path

from acm.core.errors import IOFailureError
from acm.engine.model import NOT_EXIST


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_of(data: bytes | None) -> str:
    return NOT_EXIST if data is None else sha256_hex(data)


def read_bytes(path: Path) -> bytes | None:
    """File content, or None when it does not exist."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise IOFailureError(f"cannot read {path}: {e}") from e


def atomic_write(path: Path, data: bytes, *, new_file_mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically.

    A symlink is followed (the target is replaced, the link stays); a file with other hard
    links is rewritten in place so the links keep seeing it; mode and, when permitted,
    ownership are preserved. New files get ``new_file_mode``.
    """
    target = Path(os.path.realpath(path))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            st: os.stat_result | None = target.stat()
        except FileNotFoundError:
            st = None
        if st is not None and st.st_nlink > 1:
            with open(target, "r+b") as f:
                f.write(data)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            return
        tmp = target.with_name(f".{target.name}.acm_tmp")
        mode = stat.S_IMODE(st.st_mode) if st is not None else new_file_mode
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, mode)
            if st is not None:
                with contextlib.suppress(OSError):
                    os.chown(tmp, st.st_uid, st.st_gid)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        with contextlib.suppress(OSError):
            dfd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except OSError as e:
        raise IOFailureError(f"cannot write {path}: {e}") from e


def remove_file(path: Path) -> None:
    try:
        os.unlink(os.path.realpath(path))
    except FileNotFoundError:
        return
    except OSError as e:
        raise IOFailureError(f"cannot remove {path}: {e}") from e


def cleanup_stale_tmp(*dirs: Path) -> None:
    """Remove leftovers of interrupted writes (``.*.acm_tmp``)."""
    for d in dirs:
        if d.is_dir():
            for p in d.glob(".*.acm_tmp"):
                with contextlib.suppress(OSError):
                    p.unlink()
