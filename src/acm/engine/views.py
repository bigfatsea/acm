"""Read-only views over the history: field changes per record, and pruning."""

import dataclasses
from dataclasses import dataclass
from typing import Any

from acm.core.context import Ctx
from acm.core.errors import ACMError
from acm.engine.history import WRITE_KINDS, HistoryLog, ObjectStore, Record
from acm.formats.base import MISSING, KeyPath, parse, strict_equal

FORMAT_BY_SUFFIX = {
    ".json": "json", ".jsonc": "jsonc", ".json5": "json5",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
}  # fmt: skip


@dataclass(frozen=True)
class FieldChange:
    path: KeyPath
    before: Any
    after: Any


def guess_format(file: str) -> str | None:
    for suffix, fmt in FORMAT_BY_SUFFIX.items():
        if file.endswith(suffix):
            return fmt
    return None


def record_changes(store: ObjectStore, rec: Record, fmt: str | None = None) -> list[FieldChange]:
    """Which managed fields this record changed (values from the stored versions)."""
    fmt = fmt or guess_format(rec.file)
    if rec.kind not in WRITE_KINDS or fmt is None or rec.owned:
        return []
    try:
        b, a = store.get(rec.before), store.get(rec.after)
        bdoc = parse(fmt, b) if b is not None else None
        adoc = parse(fmt, a) if a is not None else None
    except ACMError:
        return []
    out: list[FieldChange] = []
    for p in rec.paths:
        bv = MISSING if bdoc is None else bdoc.get(p)
        av = MISSING if adoc is None else adoc.get(p)
        if not strict_equal(bv, av):
            out.append(FieldChange(p, bv, av))
    return out


def prune(ctx: Ctx, keep: int) -> tuple[int, int]:
    """Keep each file's baseline and its newest ``keep`` records; drop the rest.

    Paths of dropped records are folded into the baseline record so field restores still know
    every path acm ever managed. Returns (records removed, objects removed)."""
    log, store = HistoryLog(ctx), ObjectStore(ctx)
    records = log.read()
    by_file: dict[tuple[str, str], list[Record]] = {}
    for r in records:
        by_file.setdefault((r.agent, r.file), []).append(r)
    drop: set[int] = set()
    folded: dict[tuple[str, str], dict[KeyPath, None]] = {}
    for key, recs in by_file.items():
        writes = [r for r in recs if r.kind != "baseline"]
        for r in writes[: max(len(writes) - keep, 0)]:
            drop.add(r.seq)
            folded.setdefault(key, {}).update(dict.fromkeys(r.paths))
    if not drop:
        return 0, 0
    kept: list[Record] = []
    for r in records:
        if r.seq in drop:
            continue
        if r.kind == "baseline" and (r.agent, r.file) in folded:
            merged = dict.fromkeys(r.paths)
            merged.update(folded[(r.agent, r.file)])
            r = dataclasses.replace(r, paths=tuple(merged))
        kept.append(r)
    log.rewrite(kept)
    referenced = {h for r in kept for h in (r.before, r.after)}
    removed = 0
    for h in store.all_hashes() - referenced:
        store.delete(h)
        removed += 1
    return len(drop), removed


def unmanaged_changes(store: ObjectStore, rec: Record, fmt: str) -> list[FieldChange]:
    """Fields outside ``rec.paths`` that differ between the record's two versions."""
    from acm.formats.base import changed_paths

    try:
        b, a = store.get(rec.before), store.get(rec.after)
        bt = parse(fmt, b).tree() if b is not None else {}
        at = parse(fmt, a).tree() if a is not None else {}
    except ACMError:
        return []

    def get(tree: Any, path: KeyPath) -> Any:
        for seg in path:
            try:
                tree = tree[seg]
            except (KeyError, IndexError, TypeError):
                return MISSING
        return tree

    out: list[FieldChange] = []
    for p in changed_paths(bt, at):
        if any(p[: len(m)] == m or m[: len(p)] == p for m in rec.paths):
            continue
        out.append(FieldChange(p, get(bt, p), get(at, p)))
    return out
