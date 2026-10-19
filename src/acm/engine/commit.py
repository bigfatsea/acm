"""The only code path that writes managed files: baseline, versions, atomic write, history."""

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from acm.core.context import Ctx
from acm.core.errors import ACMError, IOFailureError, SafetyBlockedError
from acm.engine.fsio import atomic_write, hash_of, read_bytes, remove_file
from acm.engine.history import HistoryLog, ObjectStore, Record, now_iso
from acm.engine.model import FileSpec
from acm.formats.base import KeyPath


@dataclass
class FileChange:
    spec: FileSpec
    before: bytes | None
    after: bytes | None
    paths: tuple[KeyPath, ...]
    external_before: bool = False


def _fault(ctx: Ctx, name: str) -> None:
    """Test-only fault injection (``ACM_TEST_FAULT_<NAME>=1``)."""
    if ctx.env.get(f"ACM_TEST_FAULT_{name}") == "1":
        if ctx.env.get("ACM_TEST_FAULT_MODE") == "kill":
            os._exit(137)
        raise IOFailureError(f"injected fault: {name}")


def _put_back(spec: FileSpec, data: bytes | None) -> None:
    if data is None:
        remove_file(spec.path)
    else:
        atomic_write(spec.path, data)


def commit(
    ctx: Ctx,
    agent: str,
    changes: list[FileChange],
    *,
    op: int,
    kind: str,
    cmd: str,
    log: HistoryLog,
    store: ObjectStore,
) -> list[Path]:
    """Write ``changes`` as one transaction. On a mid-way failure every file already written is
    put back, so an agent is never left half-updated."""
    # 1. nothing may have changed since the plan was computed
    for ch in changes:
        if hash_of(read_bytes(ch.spec.path)) != hash_of(ch.before):
            raise SafetyBlockedError(
                f"{ch.spec.path} changed while acm was working; nothing was written - retry"
            )
    # 2. first write of a file: record the pristine baseline BEFORE touching anything
    for ch in changes:
        file = str(ch.spec.path)
        if log.baseline(agent, file) is None:
            h = store.put(ch.before) if ch.before is not None else hash_of(None)
            log.append(
                Record(
                    seq=log.next_seq(), time=now_iso(), op=op, agent=agent, file=file,
                    kind="baseline", cmd=cmd, before=h, after=h, paths=(), owned=ch.spec.owned,
                )
            )  # fmt: skip
    # 3. keep both versions
    hashes: list[tuple[str, str]] = []
    for ch in changes:
        b = store.put(ch.before) if ch.before is not None else hash_of(None)
        a = store.put(ch.after) if ch.after is not None else hash_of(None)
        hashes.append((b, a))
    _fault(ctx, "AFTER_OBJECTS")
    # 4. write, all-or-nothing per agent
    written: list[FileChange] = []
    try:
        for i, ch in enumerate(changes):
            if ch.before == ch.after:
                continue
            if ch.after is None:
                remove_file(ch.spec.path)
            else:
                atomic_write(ch.spec.path, ch.after)
            written.append(ch)
            if i == 0:
                _fault(ctx, "AFTER_FIRST_FILE")
    except BaseException as e:
        for w in reversed(written):
            with contextlib.suppress(ACMError, OSError):
                _put_back(w.spec, w.before)
        if isinstance(e, ACMError | KeyboardInterrupt):
            raise
        raise IOFailureError(f"write failed and was rolled back: {e}") from e
    _fault(ctx, "BEFORE_RECORD")
    # 5. history
    for ch, (b, a) in zip(changes, hashes, strict=True):
        log.append(
            Record(
                seq=log.next_seq(), time=now_iso(), op=op, agent=agent, file=str(ch.spec.path),
                kind=kind, cmd=cmd, before=b, after=a, paths=ch.paths, owned=ch.spec.owned,
                external_before=ch.external_before,
            )
        )  # fmt: skip
    return [w.spec.path for w in written]
