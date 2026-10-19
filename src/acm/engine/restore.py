"""Restore managed files to an earlier version (fields by default, whole file on request)."""

from dataclasses import dataclass
from typing import Literal

from acm.core.context import Ctx
from acm.core.errors import ACMError, NotFoundError, SafetyBlockedError
from acm.engine.commit import FileChange, commit
from acm.engine.evaluate import assert_non_destructive, explained
from acm.engine.fsio import read_bytes
from acm.engine.history import WRITE_KINDS, HistoryLog, ObjectStore
from acm.engine.model import (
    AdapterLike,
    ApplyResult,
    Diff,
    FileSpec,
    Interaction,
    ProjectionWarning,
)
from acm.engine.unmanaged import set_unmanaged
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


@dataclass(frozen=True)
class RestoreRequest:
    target: Literal["baseline", "op", "rollback"]
    op: int | None = None
    whole_file: bool = False


def _target_hash(
    log: HistoryLog, agent: str, file: str, req: RestoreRequest, latest_op: int | None
) -> str | None:
    if req.target == "baseline":
        b = log.baseline(agent, file)
        return None if b is None else b.before
    if req.target == "op":
        assert req.op is not None
        h = log.version_at_op(agent, file, req.op)
        if h is None:
            b = log.baseline(agent, file)
            return None if b is None else b.before
        return h
    for r in log.for_file(agent, file):
        if r.op == latest_op and r.kind in WRITE_KINDS:
            return r.before
    return None


def _prune_empty_ancestors(doc: Document, target: Document, path: KeyPath) -> list[KeyPath]:
    """After deleting ``path``, drop now-empty ancestor objects the target version never had."""
    pruned: list[KeyPath] = []
    for n in range(len(path) - 1, 0, -1):
        q = path[:n]
        if target.get(q) is MISSING and doc.get(q) == {}:
            doc.delete(q)
            pruned.append(q)
        else:
            break
    return pruned


def restore_agent(
    ctx: Ctx,
    adapter: AdapterLike,
    req: RestoreRequest,
    *,
    cmd: str,
    op: int,
    log: HistoryLog,
    store: ObjectStore,
    interaction: Interaction | None = None,
) -> ApplyResult:
    inter = interaction or Interaction()
    agent = adapter.id
    res = ApplyResult(agent=agent, status="noop")
    agent_recs = [r for r in log.for_agent(agent) if r.kind in WRITE_KINDS]
    if not agent_recs:
        raise NotFoundError(f"{agent}: no acm history to restore from")
    latest_op = max(r.op for r in agent_recs)
    if req.target == "op" and req.op not in {r.op for r in log.for_agent(agent)}:
        raise NotFoundError(f"{agent}: no operation #{req.op} in the history")
    changes: list[FileChange] = []
    lost: list[tuple[str, list[KeyPath]]] = []
    try:
        for spec in adapter.files(ctx):
            ch = _plan_file(ctx, adapter, spec, req, log, store, latest_op, res, lost)
            if ch is not None:
                changes.append(ch)
    except SafetyBlockedError as e:
        res.status, res.message, res.code = "blocked", e.message, 2
        return res
    except ACMError as e:
        res.status, res.message, res.code = "error", e.message, e.exit_code
        return res
    todo = [c for c in changes if c.before != c.after]
    if not todo:
        if req.target == "baseline" and not ctx.dry_run:
            set_unmanaged(ctx, agent, True)
        return res
    if ctx.dry_run:
        res.status = "dry_run"
        return res
    if req.whole_file and any(paths for _, paths in lost) and not ctx.yes:
        flat = [p for _, ps in lost for p in ps]
        if inter.confirm_file_restore is None:
            res.status = "blocked"
            res.code = 2
            res.message = (
                "restoring whole files would discard changes outside acm's managed fields "
                f"({', '.join(fmt_path(p) for p in flat[:6])}{'…' if len(flat) > 6 else ''}); "
                "re-run with --yes to proceed"
            )
            return res
        if not inter.confirm_file_restore(agent, flat):
            res.status, res.message, res.code = "blocked", "declined by user", 2
            return res
    try:
        res.files_written = commit(
            ctx, agent, todo, op=op, kind="restore", cmd=cmd, log=log, store=store
        )
    except SafetyBlockedError as e:
        res.status, res.message, res.code = "blocked", e.message, 2
        return res
    except ACMError as e:
        res.status, res.message, res.code = "error", e.message, e.exit_code
        return res
    if req.target == "baseline":
        set_unmanaged(ctx, agent, True)
    res.status = "written"
    return res


def _plan_file(
    ctx: Ctx,
    adapter: AdapterLike,
    spec: FileSpec,
    req: RestoreRequest,
    log: HistoryLog,
    store: ObjectStore,
    latest_op: int,
    res: ApplyResult,
    lost: list[tuple[str, list[KeyPath]]],
) -> FileChange | None:
    file = str(spec.path)
    if not log.for_file(adapter.id, file):
        return None
    h = _target_hash(log, adapter.id, file, req, latest_op)
    if h is None:
        return None
    target_bytes = store.get(h)
    before = read_bytes(spec.path)
    paths_all = tuple(log.all_paths(adapter.id, file))
    if spec.owned:
        res.diffs.extend(_owned_diff(spec, before, target_bytes))
        return FileChange(spec, before, target_bytes, ())
    if req.whole_file:
        if before is not None and target_bytes is not None:
            cur_tree = parse(spec.format, before).tree()
            tgt_tree = parse(spec.format, target_bytes).tree()
            outside = [
                c
                for c in changed_paths(cur_tree, tgt_tree)
                if not explained(c, list(paths_all), cur_tree, set())
            ]
            if outside:
                lost.append((file, outside))
        res.diffs.extend(_whole_diff(spec, before, target_bytes))
        return FileChange(spec, before, target_bytes, paths_all)
    doc = parse(spec.format, before) if before is not None else empty(spec.format)
    tdoc = parse(spec.format, target_bytes) if target_bytes is not None else empty(spec.format)
    before_tree = doc.tree()
    usable: list[KeyPath] = []
    pruned: set[KeyPath] = set()
    file_diffs: list[Diff] = []
    for p in paths_all:
        if not adapter.is_managed(spec.logical, p):
            res.warnings.append(
                ProjectionWarning(
                    fmt_path(p),
                    "no longer a managed path of this adapter; left as it is",
                    adapter.id,
                )
            )
            continue
        usable.append(p)
        tv, cv = tdoc.get(p), doc.get(p)
        if tv is MISSING:
            if cv is not MISSING:
                file_diffs.append(Diff(spec.path, p, cv, MISSING))
                doc.delete(p)
            # also sweeps empty parents left behind by earlier retired paths
            pruned.update(_prune_empty_ancestors(doc, tdoc, p))
        elif cv is MISSING or not strict_equal(tv, cv):
            file_diffs.append(Diff(spec.path, p, cv, tv))
            doc.set(p, tv)
    res.diffs.extend(file_diffs)
    if not file_diffs and not pruned:
        after = before
    elif target_bytes is None and doc.tree() == {}:
        after = None  # the file did not exist before acm and nothing of the user's remains
    else:
        after = doc.render()
    assert_non_destructive(spec, before_tree, after, usable, pruned)
    return FileChange(spec, before, after, tuple(usable))


def _owned_diff(spec: FileSpec, before: bytes | None, after: bytes | None) -> list[Diff]:
    if before == after:
        return []
    return [Diff(spec.path, (), "<file>" if before is not None else MISSING,
                 "<file>" if after is not None else MISSING)]  # fmt: skip


def _whole_diff(spec: FileSpec, before: bytes | None, after: bytes | None) -> list[Diff]:
    return _owned_diff(spec, before, after)
