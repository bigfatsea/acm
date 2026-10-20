"""Evaluate a Plan against the files on disk: drift, diffs, final bytes, safety assertions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acm.core.context import Ctx
from acm.core.errors import ACMError, FormatError, SafetyBlockedError
from acm.engine.fsio import hash_of, read_bytes
from acm.engine.history import HistoryLog, ObjectStore, Record
from acm.engine.model import (
    NOT_EXIST,
    AdapterLike,
    Delete,
    Diff,
    DriftItem,
    FileSpec,
    Op,
    OwnedFile,
    Plan,
    Set,
)
from acm.formats.base import (
    MISSING,
    Document,
    KeyPath,
    changed_paths,
    empty,
    fmt_path,
    parse,
    strict_equal,
)


@dataclass
class FileEval:
    spec: FileSpec
    before: bytes | None
    after: bytes | None
    paths: tuple[KeyPath, ...]
    ops: list[Op]
    last: Record | None
    diffs: list[Diff] = field(default_factory=list)

    @property
    def before_hash(self) -> str:
        return hash_of(self.before)

    @property
    def changed(self) -> bool:
        return self.before != self.after

    @property
    def external_before(self) -> bool:
        return self.last is not None and self.before_hash != self.last.after


@dataclass
class Evaluation:
    agent: str
    files: list[FileEval] = field(default_factory=list)
    drift: list[DriftItem] = field(default_factory=list)
    first_takeover: bool = False
    new_paths: list[tuple[Path, KeyPath]] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def diffs(self) -> list[Diff]:
        return [d for f in self.files for d in f.diffs]

    @property
    def changed(self) -> list[FileEval]:
        return [f for f in self.files if f.changed]


def related(a: KeyPath, b: KeyPath) -> bool:
    """One path is a prefix of (or equal to) the other."""
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def explained(change: KeyPath, op_paths: list[KeyPath], before: Any, extra: set[KeyPath]) -> bool:
    """Is a difference found at ``change`` justified by one of the operations?"""
    if change in extra:
        return True
    for o in op_paths:
        if change[: len(o)] == o:
            return True
        if o[: len(change)] == change:
            cur = _get(before, change)
            if cur is MISSING or isinstance(cur, list):
                return True
    return False


def _get(tree: Any, path: KeyPath) -> Any:
    node = tree
    for seg in path:
        try:
            node = node[seg]
        except (KeyError, IndexError, TypeError):
            return MISSING
    return node


def assert_non_destructive(
    spec: FileSpec,
    before_tree: Any,
    after_bytes: bytes | None,
    op_paths: list[KeyPath],
    extra: set[KeyPath] | None = None,
) -> None:
    """Re-parse what we are about to write; only the operated paths may differ."""
    if after_bytes is None:
        return
    try:
        after_tree = parse(spec.format, after_bytes).tree()
    except FormatError as e:
        raise SafetyBlockedError(f"{spec.path}: refusing to write an unparsable file ({e})") from e
    for c in changed_paths(before_tree, after_tree):
        if not explained(c, op_paths, before_tree, extra or set()):
            raise SafetyBlockedError(
                f"{spec.path}: the edit would change {fmt_path(c)}, which is outside the managed "
                "paths; nothing was written"
            )


def detect_drift(
    store: ObjectStore, spec: FileSpec, before: bytes | None, doc: Document | None, last: Record
) -> tuple[list[DriftItem], list[str]]:
    """Compare the managed fields now against what ACM last wrote."""
    if spec.owned:
        if hash_of(before) != last.after:
            return [DriftItem(spec.path, (), last.after[:12], hash_of(before)[:12])], []
        return [], []
    try:
        wrote = store.get(last.after)
    except ACMError as e:
        return [], [f"cannot verify drift for {spec.path}: {e.message}"]
    expected_doc = None if wrote is None else parse(spec.format, wrote)
    items: list[DriftItem] = []
    for p in last.paths:
        exp = MISSING if expected_doc is None else expected_doc.get(p)
        got = MISSING if doc is None else doc.get(p)
        if not strict_equal(exp, got):
            items.append(DriftItem(spec.path, p, exp, got))
    return items, []


def evaluate(
    ctx: Ctx,
    adapter: AdapterLike,
    plan: Plan,
    log: HistoryLog,
    store: ObjectStore,
    *,
    check_whitelist: bool = True,
) -> Evaluation:
    ev = Evaluation(agent=adapter.id)
    if plan.error:
        ev.error = plan.error
        return ev
    specs = {s.logical: s for s in adapter.files(ctx)}
    ops_by_file: dict[str, list[Op]] = {}
    for op in plan.ops:
        if op.file not in specs:
            ev.error = f"internal error: {adapter.id} planned an op for unknown file {op.file!r}"
            return ev
        ops_by_file.setdefault(op.file, []).append(op)
    ev.first_takeover = not any(r.kind in ("write", "restore") for r in log.for_agent(adapter.id))
    for logical, spec in specs.items():
        last = log.last_write(adapter.id, str(spec.path))
        ops = ops_by_file.get(logical, [])
        if not ops and last is None:
            continue
        try:
            fe = _evaluate_file(ctx, adapter, spec, ops, last, log, store, ev, check_whitelist)
        except FormatError as e:
            ev.error = f"{spec.path}: {e.message}"
            return ev
        if fe is not None:
            ev.files.append(fe)
    return ev


def _evaluate_file(
    ctx: Ctx,
    adapter: AdapterLike,
    spec: FileSpec,
    ops: list[Op],
    last: Record | None,
    log: HistoryLog,
    store: ObjectStore,
    ev: Evaluation,
    check_whitelist: bool,
) -> FileEval | None:
    if spec.owned:
        owned_root = (ctx.acm_home / "owned").resolve()
        if not spec.path.resolve().is_relative_to(owned_root):
            raise SafetyBlockedError(
                f"{adapter.id}: acm-owned file {spec.path} is outside {owned_root}; "
                "nothing was written"
            )
    before = read_bytes(spec.path)
    if spec.owned:
        return _evaluate_owned(spec, ops, last, before, store, ev)
    doc_before = parse(spec.format, before) if before is not None else None
    if last is not None:
        items, notes = detect_drift(store, spec, before, doc_before, last)
        ev.drift.extend(items)
        ev.notes.extend(notes)
    effective: list[Op] = list(ops)
    op_paths = [o.path for o in ops if isinstance(o, (Set, Delete))]
    if check_whitelist:
        for p in op_paths:
            if not adapter.is_managed(spec.logical, p):
                raise SafetyBlockedError(
                    f"{adapter.id}: {fmt_path(p)} in {spec.path} is outside the adapter's managed "
                    "paths (whitelist violation); nothing was written"
                )
    if last is not None:  # retire paths we wrote last time and no longer plan
        for p in last.paths:
            if not any(related(p, q) for q in op_paths):
                cur = doc_before.get(p) if doc_before is not None else MISSING
                if cur is not MISSING:
                    effective.append(Delete(spec.logical, p))
                    op_paths.append(p)
    doc = parse(spec.format, before) if before is not None else empty(spec.format)
    before_tree = doc.tree()
    diffs: list[Diff] = []
    for op in effective:
        if isinstance(op, Set):
            cur = doc.get(op.path)
            if not strict_equal(cur, op.value):
                diffs.append(Diff(spec.path, op.path, cur, op.value))
            doc.set(op.path, op.value)
        elif isinstance(op, Delete):
            cur = doc.get(op.path)
            if cur is not MISSING:
                diffs.append(Diff(spec.path, op.path, cur, MISSING))
            doc.delete(op.path)
    all_paths = tuple(dict.fromkeys(op_paths))
    new_paths = [
        p
        for p in all_paths
        if not any(related(p, q) for q in log.all_paths(adapter.id, str(spec.path)))
    ]
    ev.new_paths.extend((spec.path, p) for p in new_paths)
    if before is None and not any(isinstance(o, Set) for o in effective):
        after: bytes | None = None
    else:
        rendered = doc.render()
        after = before if (before is not None and not diffs) else rendered
    assert_non_destructive(spec, before_tree, after, op_paths)
    return FileEval(spec, before, after, all_paths, effective, last, diffs)


def _evaluate_owned(
    spec: FileSpec,
    ops: list[Op],
    last: Record | None,
    before: bytes | None,
    store: ObjectStore,
    ev: Evaluation,
) -> FileEval | None:
    if last is not None:
        items, notes = detect_drift(store, spec, before, None, last)
        ev.drift.extend(items)
        ev.notes.extend(notes)
    contents = [o.content for o in ops if isinstance(o, OwnedFile)]
    after = contents[-1] if contents else None
    if before is None and after is None:
        return None
    diffs = (
        []
        if before == after
        else [Diff(spec.path, (), "<file>" if before else MISSING, "<file>" if after else MISSING)]
    )
    return FileEval(spec, before, after, (), ops, last, diffs)


__all__ = [
    "NOT_EXIST",
    "Evaluation",
    "FileEval",
    "assert_non_destructive",
    "detect_drift",
    "evaluate",
    "explained",
    "related",
]
