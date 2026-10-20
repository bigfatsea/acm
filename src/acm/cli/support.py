"""Shared plumbing for commands: contexts, agent selection, planning, interaction."""

import sys
from dataclasses import dataclass

from acm.adapters.base import Adapter, DocView
from acm.adapters.registry import all_adapters, find_adapter
from acm.catalog.model import ResolvedTarget
from acm.catalog.resolve import (
    Catalog,
    TargetError,
    build_catalog,
    profile_providers,
    resolve_target,
)
from acm.cli.output import Out, field_line
from acm.config.schema import CoreConfig
from acm.core.context import Ctx
from acm.core.errors import ACMError, FormatError, NotFoundError, SafetyBlockedError
from acm.engine.apply import describe_drift
from acm.engine.model import ApplyResult, Diff, DriftDecision, DriftItem, Interaction, Plan
from acm.formats.base import KeyPath, fmt_path


def make_ctx(
    *, dry_run: bool = False, force: bool = False, yes: bool = False, verbose: bool = False,
    show_secrets: bool = False,
) -> Ctx:  # fmt: skip
    return Ctx.from_env(
        dry_run=dry_run, force=force, yes=yes, verbose=verbose, show_secrets=show_secrets
    )


def select_adapters(names: list[str], ctx: Ctx, *, detected_only: bool = True) -> list[Adapter]:
    """Explicitly named agents (errors if unknown/missing) or every installed one."""
    if names:
        out: list[Adapter] = []
        for n in names:
            a = find_adapter(n)
            if a is None:
                known = ", ".join(x.id for x in all_adapters())
                raise NotFoundError(f"unknown agent '{n}' (known: {known})")
            if not a.detect(ctx):
                raise NotFoundError(f"{a.name} was not detected on this machine")
            out.append(a)
        return out
    pool = all_adapters()
    return [a for a in pool if a.detect(ctx)] if detected_only else pool


@dataclass
class AgentPlan:
    adapter: Adapter
    plan: Plan
    target: ResolvedTarget | None = None


def plan_agents(
    ctx: Ctx,
    config: CoreConfig,
    profile: str,
    adapters: list[Adapter],
    *,
    strict: bool,
    catalog: Catalog | None = None,
) -> tuple[list[AgentPlan], Catalog]:
    """Resolve ``profile`` for each agent and build its Plan.

    ``strict`` (use/apply): problems affecting every agent - unreachable gateway, unknown model,
    unset environment variable - raise before anything is written. Non-strict (status) turns
    them into per-agent errors.
    """
    cat = catalog or build_catalog(ctx, config, profile_providers(config, profile))
    if strict and cat.errors:
        raise next(iter(cat.errors.values()))
    out: list[AgentPlan] = []
    for ad in adapters:
        try:
            target = resolve_target(config, cat, profile, ad.protocols, ad.id)
            plan = ad.plan_files(target, ctx, DocView(ctx, ad.files(ctx)))
            out.append(AgentPlan(ad, plan, target))
        except TargetError as e:
            out.append(AgentPlan(ad, Plan(error=str(e))))
        except FormatError as e:
            out.append(AgentPlan(ad, Plan(error=f"{ad.name}: {e.message}")))
        except ACMError as e:
            if strict and e.exit_code in (1, 3):  # config / I-O problems stop everything
                raise
            out.append(AgentPlan(ad, Plan(error=e.message)))
    return out, cat


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def choose_agents(out: Out, detected: list[Adapter], preselected: set[str]) -> list[Adapter]:
    """A checklist of the detected agents (managed ones pre-checked); returns the chosen ones."""
    chosen = {a.id for a in detected if a.id in preselected}
    while True:
        out.err("Agents to manage (managed ones are pre-selected):")
        for i, a in enumerate(detected, 1):
            mark = "x" if a.id in chosen else " "
            exp = " (experimental)" if a.tier == "T2" else ""
            out.err(f"  {i}. [{mark}] {a.name}{exp}")
        out.err("Toggle by number (e.g. 2 3), a = all, n = none, Enter = continue, q = abort")
        try:
            ans = input("> ").strip().lower()
        except EOFError:
            ans = ""
        if not ans:
            return [a for a in detected if a.id in chosen]
        if ans == "q":
            raise SafetyBlockedError("aborted")
        if ans == "a":
            chosen = {a.id for a in detected}
        elif ans == "n":
            chosen = set()
        else:
            for tok in ans.replace(",", " ").split():
                if tok.isdigit() and 1 <= int(tok) <= len(detected):
                    chosen ^= {detected[int(tok) - 1].id}


def interaction_for(out: Out, ctx: Ctx) -> Interaction:
    """Prompts, only when a terminal is attached."""
    if not ctx.interactive:
        return Interaction()

    def ask(prompt: str) -> str:
        out.err(prompt)
        try:
            return input("> ").strip().lower()
        except EOFError:
            return ""

    def resolve_drift(agent: str, items: list[DriftItem]) -> DriftDecision:
        out.err(f"{agent}: managed fields were changed outside acm:")
        out.err(describe_drift(items, ctx.show_secrets))
        a = ask("[o]verwrite with acm's values / [u]nmanage this agent / [a]bort (default)?")
        return {"o": "overwrite", "u": "unmanage"}.get(a[:1], "abort")  # type: ignore[return-value]

    def confirm_changes(agent: str, diffs: list[Diff], first: bool) -> bool:
        head = "first takeover of" if first else "new managed fields in"
        out.err(f"acm will change these fields ({head} {agent}):")
        for d in diffs:
            out.err("  " + field_line(d.path, d.current, d.desired, ctx.show_secrets))
        return ask("Proceed? [y/N]").startswith("y")

    def confirm_file_restore(agent: str, paths: list[KeyPath]) -> bool:
        out.err(f"{agent}: restoring whole files discards changes to:")
        for p in paths[:20]:
            out.err(f"  {fmt_path(p)}")
        return ask("Proceed? [y/N]").startswith("y")

    return Interaction(resolve_drift, confirm_changes, confirm_file_restore)


def report(out: Out, results: list[ApplyResult], ctx: Ctx) -> int:
    """Print one line per agent (+ details) and return the exit code."""
    code = 0
    seen: set[tuple[str, str, str]] = set()
    for r in results:
        detail = ""
        if r.status == "written":
            n = len(r.diffs)
            detail = f"{n} field{'s' if n != 1 else ''} changed" if n else "updated"
        elif r.status == "dry_run":
            detail = f"would change {len(r.diffs)} field{'s' if len(r.diffs) != 1 else ''}"
        elif r.status == "unmanaged":
            detail = r.message
        elif r.status in ("blocked", "error"):
            detail = "(reason below)"
        out.styled(f"{r.agent.ljust(14)}{r.status.ljust(11)}{detail}", r.status)
        if r.status in ("blocked", "error"):
            out.err(f"{r.agent}: {r.message}")
        if r.status == "dry_run" or ctx.verbose:
            for d in r.diffs:
                out.line("    " + field_line(d.path, d.current, d.desired, ctx.show_secrets))
        for w in r.warnings:
            key = (r.agent, w.field, w.reason)
            if key not in seen:
                seen.add(key)
                out.warn(f"[{r.agent}] {w.field}: {w.reason}")
        code = max(code, r.code)
    return code
