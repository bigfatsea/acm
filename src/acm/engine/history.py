"""Version store (content-addressed) and the append-only history log."""

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from acm.core.context import Ctx
from acm.core.errors import IOFailureError
from acm.engine.fsio import sha256_hex
from acm.engine.model import NOT_EXIST
from acm.formats.base import KeyPath

WRITE_KINDS = ("write", "restore", "auto_revert")


class ObjectStore:
    """File versions keyed by SHA-256; identical content is stored once (0600)."""

    def __init__(self, ctx: Ctx) -> None:
        self._root = ctx.objects_dir

    def _path(self, h: str) -> Path:
        return self._root / h[:2] / h

    def has(self, h: str) -> bool:
        return h == NOT_EXIST or self._path(h).is_file()

    def put(self, data: bytes) -> str:
        h = sha256_hex(data)
        p = self._path(h)
        if p.is_file():
            return h
        try:
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = p.with_name(f".{h}.acm_tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except OSError as e:
            raise IOFailureError(f"cannot store version {h[:12]}: {e}") from e
        return h

    def get(self, h: str) -> bytes | None:
        """Content of version ``h`` (None for NOT_EXIST); verified against its hash."""
        if h == NOT_EXIST:
            return None
        p = self._path(h)
        try:
            data = p.read_bytes()
        except FileNotFoundError as e:
            raise IOFailureError(f"history version {h[:12]} is missing from the store") from e
        except OSError as e:
            raise IOFailureError(f"cannot read history version {h[:12]}: {e}") from e
        if sha256_hex(data) != h:
            raise IOFailureError(f"history version {h[:12]} is corrupt (hash mismatch)")
        return data

    def all_hashes(self) -> set[str]:
        out: set[str] = set()
        if self._root.is_dir():
            for d in self._root.iterdir():
                if d.is_dir():
                    out.update(p.name for p in d.iterdir() if not p.name.startswith("."))
        return out

    def delete(self, h: str) -> None:
        with contextlib.suppress(OSError):
            self._path(h).unlink()


@dataclass(frozen=True)
class Record:
    seq: int
    time: str
    op: int
    agent: str
    file: str
    kind: str
    cmd: str
    before: str
    after: str
    paths: tuple[KeyPath, ...]
    owned: bool = False
    external_before: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "v": 1, "seq": self.seq, "time": self.time, "op": self.op, "agent": self.agent,
                "file": self.file, "kind": self.kind, "cmd": self.cmd, "before": self.before,
                "after": self.after, "paths": [list(p) for p in self.paths],
                "owned": self.owned, "external_before": self.external_before,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )  # fmt: skip

    @classmethod
    def from_obj(cls, o: dict[str, Any]) -> "Record":
        return cls(
            seq=int(o["seq"]), time=str(o["time"]), op=int(o["op"]), agent=str(o["agent"]),
            file=str(o["file"]), kind=str(o["kind"]), cmd=str(o.get("cmd", "")),
            before=str(o["before"]), after=str(o["after"]),
            paths=tuple(tuple(p) for p in o.get("paths", [])),
            owned=bool(o.get("owned", False)),
            external_before=bool(o.get("external_before", False)),
        )  # fmt: skip


class HistoryLog:
    """``history.jsonl``: one record per file per ACM write, append-only."""

    def __init__(self, ctx: Ctx) -> None:
        self._path = ctx.history_path
        self._warnings: list[str] = []
        self._cache: list[Record] | None = None

    @property
    def warnings(self) -> list[str]:
        return self._warnings

    def read(self) -> list[Record]:
        if self._cache is not None:
            return self._cache
        records: list[Record] = []
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            self._cache = records
            return records
        except OSError as e:
            raise IOFailureError(f"cannot read {self._path}: {e}") from e
        lines = raw.decode("utf-8", errors="replace").split("\n")
        last_index = max(i for i, ln in enumerate(lines) if ln.strip()) if raw.strip() else -1
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                records.append(Record.from_obj(json.loads(line)))
            except (ValueError, KeyError, TypeError):
                where = "last line (truncated write?)" if i == last_index else f"line {i + 1}"
                self._warnings.append(f"history: ignored unreadable {where}")
        self._cache = records
        return records

    def append(self, rec: Record) -> None:
        line = rec.to_json() + "\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            needs_nl = False
            if self._path.exists() and self._path.stat().st_size > 0:
                with open(self._path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    needs_nl = f.read(1) != b"\n"
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "ab") as f:
                f.write((b"\n" if needs_nl else b"") + line.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise IOFailureError(f"cannot append to {self._path}: {e}") from e
        if self._cache is not None:
            self._cache.append(rec)

    def rewrite(self, records: list[Record]) -> None:
        """Replace the whole log (``prune`` only)."""
        data = "".join(r.to_json() + "\n" for r in records).encode("utf-8")
        tmp = self._path.with_name(".history.jsonl.acm_tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except OSError as e:
            raise IOFailureError(f"cannot rewrite {self._path}: {e}") from e
        self._cache = list(records)

    # ---- queries

    def next_seq(self) -> int:
        recs = self.read()
        return (recs[-1].seq + 1) if recs else 1

    def new_op(self) -> int:
        recs = self.read()
        return (max(r.op for r in recs) + 1) if recs else 1

    def for_agent(self, agent: str) -> list[Record]:
        return [r for r in self.read() if r.agent == agent]

    def for_file(self, agent: str, file: str) -> list[Record]:
        return [r for r in self.read() if r.agent == agent and r.file == file]

    def last_write(self, agent: str, file: str) -> Record | None:
        for r in reversed(self.for_file(agent, file)):
            if r.kind in WRITE_KINDS:
                return r
        return None

    def baseline(self, agent: str, file: str) -> Record | None:
        for r in self.for_file(agent, file):
            if r.kind == "baseline":
                return r
        return None

    def all_paths(self, agent: str, file: str) -> list[KeyPath]:
        seen: dict[KeyPath, None] = {}
        for r in self.for_file(agent, file):
            if r.kind in WRITE_KINDS or r.kind == "baseline":  # baseline holds pruned paths
                for p in r.paths:
                    seen[p] = None
        return list(seen)

    def version_at_op(self, agent: str, file: str, op: int) -> str | None:
        """Hash of the file as it was right after operation ``op`` (None: not yet managed)."""
        hit: Record | None = None
        for r in self.for_file(agent, file):
            if r.op <= op:
                hit = r
        return None if hit is None else hit.after


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def warn(msg: str) -> None:
    sys.stderr.write(f"warning: {msg}\n")
