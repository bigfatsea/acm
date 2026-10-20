"""Command implementations, registered on the Typer app."""

from typing import Annotated

import typer

from acm.adapters.base import Adapter
from acm.adapters.registry import all_adapters
from acm.catalog.probe import default_gateway_url, probe_gateway
from acm.catalog.proposal import proposal_for
from acm.cli.main import app
from acm.cli.output import Out, field_line, show_value
from acm.cli.support import (
    choose_agents,
    interaction_for,
    make_ctx,
    plan_agents,
    report,
    select_adapters,
)
from acm.config.load import load_config, parse_config_text, write_config_text
from acm.core.context import Ctx
from acm.core.errors import ConfigError, NotFoundError, SafetyBlockedError
from acm.core.lock import WriteLock
from acm.engine.active import read_active, write_active
from acm.engine.apply import apply_agent
from acm.engine.fsio import cleanup_stale_tmp
from acm.engine.history import HistoryLog, ObjectStore, Record
from acm.engine.managed import load_managed, set_managed
from acm.engine.model import ApplyResult
from acm.engine.restore import RestoreRequest, restore_agent
from acm.engine.status import SEVERITY, agent_status
from acm.engine.views import prune as prune_history
from acm.engine.views import record_changes, unmanaged_changes
from acm.formats.base import fmt_path

_Agents = Annotated[list[str] | None, typer.Argument(help="Limit to these agents.")]
DryRun = Annotated[bool, typer.Option("--dry-run", help="Show what would change; write nothing.")]
Force = Annotated[bool, typer.Option("--force", help="Overwrite managed fields changed elsewhere.")]
Yes = Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")]
Verbose = Annotated[bool, typer.Option("--verbose", help="Show field-level detail.")]
Secrets = Annotated[bool, typer.Option("--show-secrets", help="Do not mask secrets in output.")]
NoColor = Annotated[bool, typer.Option("--no-color", help="Disable colors.")]


def _setup(
    dry_run: bool = False,
    force: bool = False,
    yes: bool = False,
    verbose: bool = False,
    show_secrets: bool = False,
    no_color: bool = False,
) -> tuple[Ctx, Out]:
    ctx = make_ctx(
        dry_run=dry_run, force=force, yes=yes, verbose=verbose, show_secrets=show_secrets
    )
    return ctx, Out(no_color=no_color)


# ------------------------------------------------------------------------------- init


@app.command()
def init(
    vmr: Annotated[
        str | None, typer.Option("--vmr", help="Gateway URL to read the catalog from.")
    ] = None,
    force: Force = False,
    yes: Yes = False,
    no_color: NoColor = False,
) -> None:
    """Scan agents, discover a gateway, and write ~/.acm/config.yaml after confirmation."""
    ctx, out = _setup(force=force, yes=yes, no_color=no_color)
    if ctx.config_path.exists() and not force:
        raise ConfigError(f"{ctx.config_path} already exists (use --force to regenerate it)")
    out.line("Agents on this machine:")
    for a in all_adapters():
        if a.detect(ctx):
            out.line(f"  {a.name}{' (experimental)' if a.tier == 'T2' else ''}")
    url = (vmr or default_gateway_url(ctx)).rstrip("/")
    probe = probe_gateway(ctx, url, ctx.env.get("VMR_KEY", ""))
    if probe.outcome == "auth_required":
        raise ConfigError(
            f"{url} requires a credential: export VMR_KEY=<your key> and run `acm init` again"
        )
    if probe.outcome == "none" and vmr:
        raise NotFoundError(f"no gateway found at {url}: {probe.detail}")
    if probe.outcome == "none":
        out.line("No gateway found; using the starter template.")
    else:
        what = "its Manifest" if probe.outcome == "manifest" else "its model list"
        out.line(f"Gateway at {url}: read {what}.")
    text = proposal_for(probe)
    parse_config_text(text)  # never offer a proposal that would not load
    out.line("")
    out.line(text)
    if not yes:
        if not ctx.interactive:
            raise SafetyBlockedError(
                "not writing without confirmation; re-run with --yes to write the config above"
            )
        out.err(f"Write {ctx.config_path}? [y/N]")
        if not input("> ").strip().lower().startswith("y"):
            raise SafetyBlockedError("declined")
    if ctx.config_path.exists():
        backup = ctx.config_path.with_name("config.yaml.bak")
        write_config_text(backup, ctx.config_path.read_text(encoding="utf-8"))  # 0600
        out.line(f"Previous config saved as {backup}")
    write_config_text(ctx.config_path, text)
    out.line(f"Wrote {ctx.config_path}. Next: `acm use daily` (add --dry-run to preview).")


# ----------------------------------------------------------------------- use / apply


def _project(
    ctx: Ctx, out: Out, agents: list[str], profile: str, *, cmd: str, set_active: bool
) -> int:
    config = load_config(ctx)
    if profile not in config.profiles:
        known = ", ".join(config.profiles)
        raise NotFoundError(f"profile '{profile}' not found (available: {known})")
    detected = select_adapters(agents, ctx)
    if not detected:
        out.line("No supported agents were detected on this machine.")
        return 0
    managed = load_managed(ctx)
    if agents:  # naming an agent is the explicit way to (re)include it
        chosen = detected
    else:
        pre = {a.id for a in detected} if managed is None else managed
        if ctx.interactive and not ctx.yes:
            chosen = choose_agents(out, detected, pre)
        else:
            chosen = [a for a in detected if a.id in pre]
    left_out = [a for a in detected if a not in chosen]
    if not chosen:
        out.line("No agents selected; nothing was written.")
        _report_left_out(out, ctx, left_out, managed, cmd)
        return 0
    planned, catalog = plan_agents(ctx, config, profile, chosen, strict=True)
    for note in catalog.notes():
        out.warn(note)
    cleanup_stale_tmp(*{f.path.parent for p in planned for f in p.adapter.files(ctx)})
    inter = interaction_for(out, ctx)
    results: list[ApplyResult] = []
    with WriteLock(ctx):
        store = ObjectStore(ctx)
        op = HistoryLog(ctx).new_op()
        for p in planned:
            takeover = managed is not None and p.adapter.id not in managed
            results.append(
                apply_agent(
                    ctx, p.adapter, p.plan, cmd=cmd, op=op, log=HistoryLog(ctx), store=store,
                    interaction=inter, takeover=takeover,
                )
            )  # fmt: skip
        _report_left_out(out, ctx, left_out, managed, cmd)
        projected = any(r.status in ("written", "noop") for r in results)
        if set_active and projected and not ctx.dry_run:
            write_active(ctx, profile)
    for w in HistoryLog(ctx).warnings:
        out.warn(w)
    code = report(out, results, ctx)
    if set_active and not projected and not ctx.dry_run:
        out.warn(f"no agent was projected, so the active profile was not changed to '{profile}'")
    return code


def _report_left_out(
    out: Out, ctx: Ctx, left_out: list[Adapter], managed: set[str] | None, cmd: str
) -> None:
    """Agents not selected this time; deselecting a managed one stops managing it."""
    for a in left_out:
        if managed is not None and a.id in managed:
            if not ctx.dry_run:
                set_managed(ctx, a.id, False)
            out.line(
                f"{a.id.ljust(14)}{'released'.ljust(11)}no longer managed; its files are left "
                f"as they are (`acm restore --baseline {a.id}` reverts them)"
            )
        else:
            out.line(f"{a.id.ljust(14)}{'skipped'.ljust(11)}not managed (`{cmd} {a.id}` adds it)")


@app.command()
def use(
    profile: Annotated[str, typer.Argument(help="Profile name from config.yaml.")],
    agents: _Agents = None,
    dry_run: DryRun = False,
    force: Force = False,
    yes: Yes = False,
    verbose: Verbose = False,
    show_secrets: Secrets = False,
    no_color: NoColor = False,
) -> None:
    """Make PROFILE active and project it onto the installed agents."""
    ctx, out = _setup(dry_run, force, yes, verbose, show_secrets, no_color)
    code = _project(ctx, out, agents or [], profile, cmd=f"acm use {profile}", set_active=True)
    raise typer.Exit(code)


@app.command()
def apply(
    agents: _Agents = None,
    dry_run: DryRun = False,
    force: Force = False,
    yes: Yes = False,
    verbose: Verbose = False,
    show_secrets: Secrets = False,
    no_color: NoColor = False,
) -> None:
    """Re-project the active profile (picks up gateway catalog changes)."""
    ctx, out = _setup(dry_run, force, yes, verbose, show_secrets, no_color)
    profile = read_active(ctx)
    if not profile:
        raise ConfigError("no active profile; run `acm use <profile>` first")
    code = _project(ctx, out, agents or [], profile, cmd="acm apply", set_active=False)
    raise typer.Exit(code)


# ---------------------------------------------------------------------------- status


@app.command()
def status(
    agents: _Agents = None,
    all_: Annotated[bool, typer.Option("--all", help="Also list agents not installed.")] = False,
    verbose: Verbose = False,
    show_secrets: Secrets = False,
    no_color: NoColor = False,
) -> None:
    """Show each agent's state: SYNCED, OUT_OF_SYNC, DRIFTED, ERROR, UNMANAGED, NOT_DETECTED."""
    ctx, out = _setup(verbose=verbose, show_secrets=show_secrets, no_color=no_color)
    adapters = select_adapters(agents or [], ctx, detected_only=not all_)
    config = load_config(ctx)
    active = read_active(ctx)
    planned = {}
    notes: list[str] = []
    if active and active in config.profiles:
        det = [a for a in adapters if a.detect(ctx)]
        plans, cat = plan_agents(ctx, config, active, det, strict=False)
        planned = {p.adapter.id: p for p in plans}
        notes = cat.notes()
        for name, err in cat.errors.items():
            out.warn(f"catalog '{name}': {err.message}")
    elif active:
        out.warn(f"active profile '{active}' no longer exists in config.yaml")
    log, store, managed = HistoryLog(ctx), ObjectStore(ctx), load_managed(ctx)
    worst = 0
    out.line(f"Active profile: {active or '(none)'}")
    for ad in adapters:
        ap = planned.get(ad.id)
        st = agent_status(
            ctx, ad, ap.plan if ap else None, detected=ad.detect(ctx), managed=managed,
            log=log, store=store,
        )  # fmt: skip
        detail = st.message.split("\n", 1)[0]
        if st.state == "OUT_OF_SYNC":
            detail = f"{len(st.diffs)} field(s) differ from the active profile"
        elif st.state == "DRIFTED":
            detail = f"{len(st.drift)} managed field(s) changed outside acm"
        label = ad.id + (" *" if ad.tier == "T2" else "")
        out.styled(f"{label.ljust(16)}{st.state.ljust(14)}{detail}", st.state)
        for d in st.drift:
            out.line(
                f"    drift {fmt_path(d.path)}: acm wrote "
                f"{show_value(d.path, d.expected, ctx.show_secrets)}, now "
                f"{show_value(d.path, d.found, ctx.show_secrets)}"
            )
        if ctx.verbose or st.state == "OUT_OF_SYNC":
            for df in st.diffs:
                out.line("    " + field_line(df.path, df.current, df.desired, ctx.show_secrets))
        if st.state == "ERROR" and "\n" in st.message:
            out.line("    " + st.message.split("\n", 1)[1])
        if ctx.verbose:
            for w in st.warnings:
                out.warn(f"[{ad.id}] {w.field}: {w.reason}")
        worst = max(worst, SEVERITY[st.state])
    for n in notes:
        out.warn(n)
    if any(a.tier == "T2" for a in adapters):
        out.line("* experimental (golden-tested only)")
    raise typer.Exit(2 if worst >= 2 else 0)


# --------------------------------------------------------------- history / restore


@app.command()
def history(
    agents: _Agents = None,
    full: Annotated[
        bool, typer.Option("--full", help="Also list unmanaged fields that changed.")
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Entries per file (0 = all).")] = 10,
    show_secrets: Secrets = False,
    no_color: NoColor = False,
) -> None:
    """List what acm wrote, newest first. `acm restore <op>` returns to a listed state."""
    ctx, out = _setup(show_secrets=show_secrets, no_color=no_color)
    wanted = None
    if agents:
        wanted = {a.id for a in select_adapters(agents, ctx, detected_only=False)}
    log, store = HistoryLog(ctx), ObjectStore(ctx)
    recs = [r for r in log.read() if wanted is None or r.agent in wanted]
    if not recs:
        out.line("No history yet: acm has not written any agent configuration.")
        return
    fmts = {str(s.path): s.format for a in all_adapters() for s in a.files(ctx)}
    by_file: dict[tuple[str, str], list[Record]] = {}
    for r in recs:
        by_file.setdefault((r.agent, r.file), []).append(r)
    for (agent, file), rs in by_file.items():
        out.line(f"{agent}  {file}")
        shown = list(reversed(rs))[: limit if limit > 0 else None]
        for r in shown:
            when = r.time.replace("T", " ")[:16]
            head = f"  #{r.op:<4} {when}  {r.kind.ljust(9)} {r.cmd}"
            if r.kind == "baseline":
                out.line(f"{head}  (original version saved; `acm restore --baseline`)")
                continue
            out.line(head)
            fmt = fmts.get(file)
            for c in record_changes(store, r, fmt)[:6]:
                out.line("        " + field_line(c.path, c.before, c.after, ctx.show_secrets))
            if r.external_before:
                out.line("        (the file had been changed outside acm before this write)")
            if full and fmt:
                for c in unmanaged_changes(store, r, fmt):
                    out.line(
                        "        other " + field_line(c.path, c.before, c.after, ctx.show_secrets)
                    )
    for w in log.warnings:
        out.warn(w)


def _restore(ctx: Ctx, out: Out, agents: list[str], req: RestoreRequest, cmd: str) -> int:
    adapters = select_adapters(agents, ctx, detected_only=False)
    have = {r.agent for r in HistoryLog(ctx).read()}
    adapters = [a for a in adapters if a.id in have]
    if not adapters:
        raise NotFoundError("nothing to restore: acm has no history for the selected agents")
    inter = interaction_for(out, ctx)
    results: list[ApplyResult] = []
    first_error: NotFoundError | None = None
    with WriteLock(ctx):
        store = ObjectStore(ctx)
        op = HistoryLog(ctx).new_op()
        for a in adapters:
            try:
                results.append(
                    restore_agent(
                        ctx, a, req, cmd=cmd, op=op, log=HistoryLog(ctx), store=store,
                        interaction=inter,
                    )
                )  # fmt: skip
            except NotFoundError as e:
                first_error = first_error or e
                if agents:
                    raise
                out.warn(f"{a.id}: {e.message}")
    if not results and first_error is not None:
        raise first_error
    return report(out, results, ctx)


@app.command()
def restore(
    refs: Annotated[
        list[str] | None,
        typer.Argument(help="An operation number (see `acm history`) and/or agents."),
    ] = None,
    baseline: Annotated[
        bool, typer.Option("--baseline", help="Return to the state before acm.")
    ] = False,
    file: Annotated[
        bool, typer.Option("--file", help="Restore whole files, not only managed fields.")
    ] = False,
    dry_run: DryRun = False,
    yes: Yes = False,
    verbose: Verbose = False,
    show_secrets: Secrets = False,
    no_color: NoColor = False,
) -> None:
    """Restore managed fields (or whole files) to an earlier version. Restores can be undone."""
    ctx, out = _setup(
        dry_run=dry_run, yes=yes, verbose=verbose, show_secrets=show_secrets, no_color=no_color
    )
    ops = [int(r) for r in (refs or []) if r.isdigit()]
    names = [r for r in (refs or []) if not r.isdigit()]
    if baseline == bool(ops) or len(ops) > 1:
        raise ConfigError(
            "give exactly one of: an operation number (see `acm history`) or --baseline"
        )
    if baseline:
        req = RestoreRequest("baseline", whole_file=file)
        cmd = "acm restore --baseline"
    else:
        req = RestoreRequest("op", ops[0], whole_file=file)
        cmd = f"acm restore {ops[0]}"
    raise typer.Exit(_restore(ctx, out, names, req, cmd))


@app.command()
def rollback(
    agents: _Agents = None,
    dry_run: DryRun = False,
    yes: Yes = False,
    verbose: Verbose = False,
    show_secrets: Secrets = False,
    no_color: NoColor = False,
) -> None:
    """Undo the latest acm operation for each agent (managed fields only)."""
    ctx, out = _setup(
        dry_run=dry_run, yes=yes, verbose=verbose, show_secrets=show_secrets, no_color=no_color
    )
    raise typer.Exit(_restore(ctx, out, agents or [], RestoreRequest("rollback"), "acm rollback"))


@app.command()
def prune(
    keep: Annotated[
        int, typer.Option("--keep", min=1, help="Recent entries to keep per file (>= 1).")
    ],
    no_color: NoColor = False,
) -> None:
    """Delete old history entries and unreferenced versions (baselines are always kept)."""
    ctx, out = _setup(no_color=no_color)
    with WriteLock(ctx):
        removed, objects = prune_history(ctx, keep)
    out.line(f"Removed {removed} history entries and {objects} stored versions.")


# ------------------------------------------------------------------------------- run


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    agent: Annotated[str, typer.Argument(help="Agent to launch, e.g. claude, codex, opencode.")],
    args: Annotated[list[str] | None, typer.Argument(help="Arguments passed to the agent.")] = None,
    model: Annotated[
        str | None, typer.Option("-m", "--model", help="Model, e.g. vmr.coding or vmr@fast.")
    ] = None,
    profile: Annotated[str | None, typer.Option("--profile", help="Profile to use.")] = None,
    manifest: Annotated[
        str | None, typer.Option("--manifest", help="Manifest URL or file.")
    ] = None,
    no_color: NoColor = False,
) -> None:
    """Start AGENT once with the configured models; nothing is written to its configuration."""
    from acm.run.runner import run_agent

    ctx, out = _setup(no_color=no_color)
    code = run_agent(
        ctx, out, agent, model=model, profile=profile, manifest=manifest,
        passthrough=list(args or []),
    )  # fmt: skip
    raise typer.Exit(code)
