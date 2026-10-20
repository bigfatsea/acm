"""Apply a Plan to one agent: drift handling, confirmation, dry-run, commit."""

from acm.core.context import Ctx
from acm.core.errors import ACMError, SafetyBlockedError
from acm.core.masking import mask_value_at
from acm.engine.commit import FileChange, commit
from acm.engine.evaluate import Evaluation, evaluate
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.managed import set_managed
from acm.engine.model import (
    NOT_EXIST,
    AdapterLike,
    ApplyResult,
    Diff,
    DriftItem,
    Interaction,
    Plan,
)
from acm.formats.base import MISSING, fmt_path, leaf_changes


def _show(path: tuple[str | int, ...], value: object, show_secrets: bool) -> str:
    if value is MISSING:
        return "(absent)"
    return repr(mask_value_at(path, value, show_secrets))


def describe_drift(items: list[DriftItem], show_secrets: bool = False) -> str:
    lines = []
    for d in items:
        if not d.path:  # a file acm owns: the values are content hashes
            gone = d.found == NOT_EXIST[:12]
            lines.append(f"  {d.file}: {'deleted' if gone else 'changed'} since acm wrote it")
            continue
        for p, expected, found in leaf_changes(d.path, d.expected, d.found):
            lines.append(
                f"  {d.file} {fmt_path(p)}: acm wrote {_show(p, expected, show_secrets)}, "
                f"now {_show(p, found, show_secrets)}"
            )
    return "\n".join(lines)


def apply_agent(
    ctx: Ctx,
    adapter: AdapterLike,
    plan: Plan,
    *,
    cmd: str,
    op: int,
    log: HistoryLog,
    store: ObjectStore,
    interaction: Interaction | None = None,
    takeover: bool = False,
) -> ApplyResult:
    """Project ``plan`` onto one agent. Never raises for agent-level problems: they are returned
    as ``blocked`` / ``error`` results so a batch can continue with the other agents.

    ``takeover``: the agent is not in the managed set yet, so a write needs the same
    confirmation as a first takeover even when acm wrote it before."""
    inter = interaction or Interaction()
    res = ApplyResult(agent=adapter.id, status="noop", warnings=list(plan.warnings))
    try:
        ev = evaluate(ctx, adapter, plan, log, store)
    except SafetyBlockedError as e:
        res.status, res.message, res.code = "blocked", e.message, 2
        return res
    if ev.error:
        res.status, res.message, res.code = "error", ev.error, 2
        return res
    res.drift = ev.drift
    res.diffs = ev.diffs
    if ev.drift and not ctx.force:
        decision = inter.resolve_drift(adapter.id, ev.drift) if inter.resolve_drift else None
        if decision == "unmanage":
            set_managed(ctx, adapter.id, False)
            res.status, res.message = "unmanaged", "acm will no longer manage this agent"
            return res
        if decision != "overwrite":
            res.status = "blocked"
            res.code = 2
            res.message = (
                "managed fields were changed outside acm:\n"
                + describe_drift(ev.drift, ctx.show_secrets)
                + "\nre-run with --force to overwrite them"
                + (" (or answer the prompt)" if inter.resolve_drift else "")
            )
            return res
    changed = ev.changed
    if not changed:
        if not ctx.dry_run:
            set_managed(ctx, adapter.id, True)
        return res
    if ctx.dry_run:
        res.status = "dry_run"
        return res
    needs_confirm = ev.first_takeover or takeover or bool(ev.new_paths)
    if needs_confirm and not ctx.yes:
        if inter.confirm_changes is None:
            res.status = "blocked"
            res.code = 2
            res.message = (
                "first takeover or new managed fields need confirmation; re-run with --yes "
                "(use --dry-run to preview)"
            )
            return res
        if not inter.confirm_changes(adapter.id, ev.diffs, ev.first_takeover or takeover):
            res.status, res.message, res.code = "blocked", "declined by user", 2
            return res
    try:
        written = commit(
            ctx,
            adapter.id,
            _changes(ev),
            op=op,
            kind="write",
            cmd=cmd,
            log=log,
            store=store,
        )
    except SafetyBlockedError as e:
        res.status, res.message, res.code = "blocked", e.message, 2
        return res
    except ACMError as e:
        res.status, res.message, res.code = "error", e.message, e.exit_code
        return res
    set_managed(ctx, adapter.id, True)
    res.status = "written"
    res.files_written = written
    return res


def _changes(ev: Evaluation) -> list[FileChange]:
    return [
        FileChange(f.spec, f.before, f.after, f.paths, external_before=f.external_before)
        for f in ev.files
        if f.changed
    ]


def format_diffs(diffs: list[Diff], show_secrets: bool = False) -> list[str]:
    return [
        f"{d.file}: {fmt_path(d.path) or '<file>'}: "
        f"{_show(d.path, d.current, show_secrets)} -> {_show(d.path, d.desired, show_secrets)}"
        for d in diffs
    ]
