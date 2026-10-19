"""Plain data types shared by adapters and the engine."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from acm.formats.base import KeyPath

NOT_EXIST = "-"  # version hash of a file that does not exist


@dataclass(frozen=True)
class FileSpec:
    """One file an adapter manages. ``owned`` files are ACM-generated and wholly ACM's."""

    logical: str
    path: Path
    format: str
    owned: bool = False


@dataclass(frozen=True)
class Set:
    file: str
    path: KeyPath
    value: Any


@dataclass(frozen=True)
class Delete:
    file: str
    path: KeyPath


@dataclass(frozen=True)
class OwnedFile:
    file: str
    content: bytes


Op = Set | Delete | OwnedFile


@dataclass(frozen=True)
class ProjectionWarning:
    """Something the target agent cannot express; always shown on stderr."""

    field: str
    reason: str
    agent: str = ""


@dataclass
class Plan:
    ops: list[Op] = field(default_factory=list)
    warnings: list[ProjectionWarning] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class DriftItem:
    file: Path
    path: KeyPath
    expected: Any  # what ACM last wrote
    found: Any  # what is there now (MISSING when absent)


@dataclass(frozen=True)
class Diff:
    """A managed field whose current value differs from the desired one."""

    file: Path
    path: KeyPath
    current: Any
    desired: Any


DriftDecision = Literal["overwrite", "unmanage", "abort"]


@dataclass
class Interaction:
    """Interactive hooks; any hook left as None means "not interactive" (block or need --yes)."""

    resolve_drift: Callable[[str, list[DriftItem]], DriftDecision] | None = None
    confirm_changes: Callable[[str, list[Diff], bool], bool] | None = None
    confirm_file_restore: Callable[[str, list[KeyPath]], bool] | None = None


@dataclass
class ApplyResult:
    agent: str
    status: Literal["written", "noop", "dry_run", "unmanaged", "blocked", "error"]
    diffs: list[Diff] = field(default_factory=list)
    warnings: list[ProjectionWarning] = field(default_factory=list)
    drift: list[DriftItem] = field(default_factory=list)
    message: str = ""
    files_written: list[Path] = field(default_factory=list)
    code: int = 0  # exit-code contribution: 0 ok, 2 blocked/error, 3 I/O failure


class AdapterLike:
    """The part of an adapter the engine relies on (full contract: ``adapters.base.Adapter``)."""

    id: str
    name: str

    def files(self, ctx: Any) -> list[FileSpec]:
        raise NotImplementedError

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        raise NotImplementedError
