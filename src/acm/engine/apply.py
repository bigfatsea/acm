"""Apply a Plan to one agent: drift handling, confirmation, dry-run, commit."""

from acm.core.context import Ctx
from acm.core.errors import ACMError, SafetyBlockedError
from acm.engine.commit import FileChange, commit
from acm.engine.evaluate import Evaluation, evaluate
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.model import (
    AdapterLike,
    ApplyResult,
    Diff,
    DriftItem,
    Interaction,
    Plan,
)
from acm.engine.unmanaged import set_unmanaged
from acm.formats.base import fmt_path


def describe_drift(items: list[DriftItem]) -> str:
    lines = []
    for d in items:
        where = f"{d.file}" + (f" {fmt_path(d.path)}" if d.path else "")
        lines.append(f"  {where}: acm wrote {d.expected!r}, now {d.found!r}")
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
) -> ApplyResult:
    """Project ``plan`` onto one agent. Never raises for agent-level problems: they are returned
    as ``blocked`` / ``error`` results so a batch can continue with the other agents."""
    inter = interaction or Interaction()
    res = ApplyResult(agent=adapter.id, status="noop", warnings=list(plan.warnings))
    try:
        ev = evaluate(ctx, adapter, plan, log, store)
    except SafetyBlockedError as e:
        res.status, res.message = "blocked", e.message
        return res
    if ev.error:
        res.status, res.message = "error", ev.error
        return res
    res.drift = ev.drift
    res.diffs = ev.diffs
    if ev.drift and not ctx.force:
        decision = inter.resolve_drift(adapter.id, ev.drift) if inter.resolve_drift else None
        if decision == "unmanage":
            set_unmanaged(ctx, adapter.id, True)
            res.status, res.message = "unmanaged", "acm will no longer manage this agent"
            return res
        if decision != "overwrite":
            res.status = "blocked"
            res.message = (
                "managed fields were changed outside acm:\n"
                + describe_drift(ev.drift)
                + "\nre-run with --force to overwrite them"
                + (" (or answer the prompt)" if inter.resolve_drift else "")
            )
            return res
    changed = ev.changed
    if not changed:
        if not ctx.dry_run:
            set_unmanaged(ctx, adapter.id, False)
        return res
    if ctx.dry_run:
        res.status = "dry_run"
        return res
    needs_confirm = ev.first_takeover or bool(ev.new_paths)
    if needs_confirm and not ctx.yes:
        if inter.confirm_changes is None:
            res.status = "blocked"
            res.message = (
                "first takeover or new managed fields need confirmation; re-run with --yes "
                "(use --dry-run to preview)"
            )
            return res
        if not inter.confirm_changes(adapter.id, ev.diffs, ev.first_takeover):
            res.status, res.message = "blocked", "declined by user"
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
        res.status, res.message = "blocked", e.message
        return res
    except ACMError as e:
        res.status, res.message = "error", e.message
        return res
    set_unmanaged(ctx, adapter.id, False)
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
    from acm.core.masking import mask_value_at
    from acm.formats.base import MISSING

    def v(path: tuple[str | int, ...], x: object) -> str:
        if x is MISSING:
            return "(absent)"
        return repr(mask_value_at(path, x, show_secrets))

    return [
        f"{d.file}: {fmt_path(d.path) or '<file>'}: "
        f"{v(d.path, d.current)} -> {v(d.path, d.desired)}"
        for d in diffs
    ]
