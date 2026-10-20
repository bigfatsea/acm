"""OpenClaw (``~/.openclaw/openclaw.json``, JSON5). Support matrix §4.5 / §7.

Persistent projection follows the official configuration docs (models.providers.<id>,
agents.defaults.model.primary, agents.defaults.utilityModel). No OpenClaw install was available
when this adapter was written, so it has golden coverage only; see the execution summary.
"""

import json
from pathlib import Path
from typing import Any

from acm.adapters.base import (
    Adapter,
    DocView,
    LaunchContext,
    LaunchSpec,
    alias_for,
    display_name,
    groups,
    launch_notes,
    run_key_vars,
)
from acm.catalog.model import ResolvedModel, ResolvedTarget
from acm.core.context import Ctx
from acm.engine.model import Delete, FileSpec, Op, Plan, ProjectionWarning, Set
from acm.formats.base import MISSING, KeyPath

DUMMY_KEY = "dummy"  # providers other than openai-completions need a placeholder when keyless
_INCLUDE_PATHS: tuple[KeyPath, ...] = (
    ("$include",),
    ("agents", "$include"),
    ("agents", "defaults", "$include"),
    ("models", "$include"),
    ("models", "providers", "$include"),
)


def ref(m: ResolvedModel) -> str:
    return f"{alias_for(m.provider, m.protocol)}/{m.id}"


def model_entry(m: ResolvedModel, label: str | None) -> dict[str, Any]:
    c = m.card
    e: dict[str, Any] = {"id": m.id, "name": display_name(m, label)}
    if c.reasoning:
        e["reasoning"] = True
    if "image" in c.input:
        e["input"] = ["text", "image"]
    if c.effective_context:
        e["contextWindow"] = c.effective_context
    if c.output:
        e["maxTokens"] = c.output
    return e


class OpenClaw(Adapter):
    id = "openclaw"
    name = "OpenClaw"
    aliases = ("claw",)
    bins = ("openclaw",)
    protocols = ("openai-completions", "anthropic-messages", "openai-responses")

    def config_path(self, ctx: Ctx) -> Path:
        p = ctx.env.get("OPENCLAW_CONFIG_PATH", "").strip()
        if p and ctx.expand(p).is_absolute():
            return ctx.expand(p)
        return ctx.home / ".openclaw" / "openclaw.json"

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return [self.config_path(ctx).parent]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        return [FileSpec("config", self.config_path(ctx), "json5")]

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical != "config":
            return False
        if len(path) == 3 and path[:2] == ("models", "providers"):
            return True
        return path in (
            ("agents", "defaults", "model"),
            ("agents", "defaults", "model", "primary"),
            ("agents", "defaults", "utilityModel"),
            ("agents", "defaults", "utilityModel", "primary"),
        )

    # ------------------------------------------------------------------ helpers

    def _providers(
        self, target: ResolvedTarget, ctx: Ctx, warns: list[ProjectionWarning]
    ) -> dict[str, dict[str, Any]]:
        labels = {(m.provider.name, m.id, m.protocol): lab for lab, m in target.members.items()}
        out: dict[str, dict[str, Any]] = {}
        for (_p, proto), models in groups(target).items():
            first = models[0]
            alias = alias_for(first.provider, proto)
            cred = first.provider.credential
            value = cred.resolve(ctx.env)
            obj: dict[str, Any] = {"baseUrl": first.base_url, "api": proto}
            if cred.is_reference and ctx.env.get(cred.var or "", "") != "":
                obj["apiKey"] = f"${{{cred.var}}}"
            elif value:
                obj["apiKey"] = value
                warns.append(
                    ProjectionWarning(
                        "api_key", "written in plain text (config.yaml holds a literal)", self.id
                    )
                )
            elif proto == "openai-completions":
                obj["auth"] = "none"
            else:
                obj["apiKey"] = DUMMY_KEY
            if first.provider.headers:
                obj["headers"] = dict(first.provider.headers)
            obj["models"] = [
                model_entry(m, labels.get((m.provider.name, m.id, m.protocol))) for m in models
            ]
            out[alias] = obj
        return out

    def _warnings(self, target: ResolvedTarget) -> list[ProjectionWarning]:
        warns = list(target.warnings)
        for role in ("reasoning", "subagent", "review"):
            if target.roles.get(role) is not None:
                warns.append(
                    ProjectionWarning(
                        f"roles.{role}", "OpenClaw has no slot for this role", self.id
                    )
                )
        return warns

    # --------------------------------------------------------------- persistent

    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan:
        for p in _INCLUDE_PATHS:
            if view.get("config", p) is not MISSING:
                return Plan(
                    error=(
                        f"{self.config_path(ctx)} uses $include; acm cannot tell which file holds "
                        "the model settings, so it will not edit it"
                    )
                )
        d = target.default
        warns = self._warnings(target)
        providers = self._providers(target, ctx, warns)
        ops: list[Op] = [Set("config", ("models", "providers", a), o) for a, o in providers.items()]
        ops.append(self._slot(view, ("agents", "defaults", "model"), ref(d)))
        fast = target.roles.get("fast")
        if fast:
            ops.append(self._slot(view, ("agents", "defaults", "utilityModel"), ref(fast)))
        else:
            ops.append(Delete("config", ("agents", "defaults", "utilityModel")))
        return Plan(ops=ops, warnings=warns)

    @staticmethod
    def _slot(view: DocView, path: KeyPath, value: str) -> Op:
        """A model slot may be a string or ``{primary, fallbacks}``; keep the user's shape."""
        if isinstance(view.get("config", path), dict):
            return Set("config", (*path, "primary"), value)
        return Set("config", path, value)

    # ----------------------------------------------------------------- one-shot

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        d = target.default
        warns = self._warnings(target)
        providers = self._providers(target, ctx, warns)
        key_vars, env_out = run_key_vars(target, ctx)
        secret_env = set(env_out)
        for (pname, proto), models in groups(target).items():
            if pname in key_vars:
                providers[alias_for(models[0].provider, proto)]["apiKey"] = (
                    f"${{{key_vars[pname]}}}"
                )
        override: dict[str, Any] = {"models": {"providers": providers}}
        fast = target.roles.get("fast")
        if fast:
            override["agents"] = {"defaults": {"utilityModel": ref(fast)}}
        argv = [
            launch.bin_path or "openclaw", "agent", "exec",
            "--config-override", json.dumps(override, ensure_ascii=False, separators=(",", ":")),
            "--model", ref(d), *launch.passthrough,
        ]  # fmt: skip
        notes = launch_notes(warns)
        notes.append(
            "OpenClaw runs one task (`agent exec`); interactive use goes through its Gateway "
            "and needs `acm use`. Environment substitution inside --config-override is "
            "unverified on a real install."
        )
        return LaunchSpec(argv=argv, env=env_out, mode="exec", notes=notes, secret_env=secret_env)
