"""Hermes Agent (``~/.hermes/config.yaml``). Support matrix §4.6 / §7.

Verified against hermes-agent source (hermes_cli/config_providers.py, runtime_provider_custom.py,
agent/auxiliary_client.py): a ``providers.<name>`` entry is selectable as
``model.provider: custom:<name>`` and also by auxiliary tasks and ``delegation``.
"""

from pathlib import Path
from typing import Any

from acm.adapters.base import (
    Adapter,
    DocView,
    LaunchContext,
    LaunchSpec,
    LaunchUnsupportedError,
    alias_for,
    groups,
)
from acm.catalog.model import ResolvedModel, ResolvedTarget
from acm.core.context import Ctx
from acm.engine.model import Delete, FileSpec, Op, Plan, ProjectionWarning, Set
from acm.formats.base import MISSING, KeyPath

API_MODE = {
    "openai-completions": "chat_completions",
    "anthropic-messages": "anthropic_messages",
    "openai-responses": "codex_responses",
}
AUX_TASKS = ("title_generation", "compression", "web_extract", "approval")
_AUX_KEYS = ("provider", "model", "base_url", "api_key")
_MODEL_KEYS = ("default", "provider", "base_url", "api_mode", "context_length")
PREFIX = "acm-"  # keeps our entries clear of Hermes' built-in provider names


def hermes_name(m: ResolvedModel) -> str:
    return PREFIX + alias_for(m.provider, m.protocol).lower()


def ref(m: ResolvedModel) -> str:
    return f"custom:{hermes_name(m)}"


class Hermes(Adapter):
    id = "hermes"
    name = "Hermes Agent"
    aliases = ("hermes-agent",)
    bins = ("hermes",)
    protocols = ("openai-completions", "anthropic-messages", "openai-responses")

    def home(self, ctx: Ctx) -> Path:
        d = ctx.env.get("HERMES_HOME", "").strip()
        return ctx.expand(d) if d and ctx.expand(d).is_absolute() else ctx.home / ".hermes"

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return [self.home(ctx)]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        return [FileSpec("config", self.home(ctx) / "config.yaml", "yaml")]

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical != "config":
            return False
        if path == ("model",):
            return True
        if len(path) == 2 and path[0] == "model":
            return path[1] in _MODEL_KEYS
        if len(path) == 2 and path[0] == "providers":
            return isinstance(path[1], str) and path[1].startswith(PREFIX)
        if len(path) == 3 and path[0] == "auxiliary":
            return path[1] in AUX_TASKS and path[2] in _AUX_KEYS
        return len(path) == 2 and path[0] == "delegation" and path[1] in ("provider", "model")

    # ------------------------------------------------------------------ helpers

    def _provider_entries(
        self, target: ResolvedTarget, ctx: Ctx, warns: list[ProjectionWarning]
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for (_p, _proto), models in groups(target).items():
            first = models[0]
            cred = first.provider.credential
            entry: dict[str, Any] = {
                "base_url": first.base_url,
                "api_mode": API_MODE[first.protocol],
                "models": {m.id: {} for m in models},
            }
            value = cred.resolve(ctx.env)
            if cred.is_reference and ctx.env.get(cred.var or "", "") != "":
                entry["key_env"] = cred.var
            elif value:
                entry["api_key"] = value
                warns.append(
                    ProjectionWarning(
                        "api_key", "written in plain text (config.yaml holds a literal)", self.id
                    )
                )
            if first.provider.headers:
                entry["extra_headers"] = dict(first.provider.headers)
            out[hermes_name(first)] = entry
        return out

    def _warnings(self, target: ResolvedTarget) -> list[ProjectionWarning]:
        warns = list(target.warnings)
        for role in ("reasoning", "review"):
            if target.roles.get(role) is not None:
                warns.append(
                    ProjectionWarning(f"roles.{role}", "Hermes has no slot for this role", self.id)
                )
        return warns

    # --------------------------------------------------------------- persistent

    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan:
        d = target.default
        warns = self._warnings(target)
        entries = self._provider_entries(target, ctx, warns)
        ops: list[Op] = [Set("config", ("providers", n), e) for n, e in entries.items()]
        current = view.get("config", ("model",))
        if current is MISSING or current is None or isinstance(current, str):
            # a fresh install keeps `model: ""` (or a bare model name): replace it by the mapping
            model_map: dict[str, Any] = {
                "default": d.id, "provider": ref(d), "base_url": "",
            }  # fmt: skip
            if d.card.effective_context:
                model_map["context_length"] = d.card.effective_context
            ops.append(Set("config", ("model",), model_map))
        else:
            ops += [
                Set("config", ("model", "default"), d.id),
                Set("config", ("model", "provider"), ref(d)),
                Set("config", ("model", "base_url"), ""),
                Delete("config", ("model", "api_mode")),
            ]
            if d.card.effective_context:
                ops.append(Set("config", ("model", "context_length"), d.card.effective_context))
        fast = target.roles.get("fast")
        if fast:
            for task in AUX_TASKS:
                ops += [
                    Set("config", ("auxiliary", task, "provider"), ref(fast)),
                    Set("config", ("auxiliary", task, "model"), fast.id),
                    Set("config", ("auxiliary", task, "base_url"), ""),
                    Set("config", ("auxiliary", task, "api_key"), ""),
                ]
        sub = target.roles.get("subagent")
        if sub:
            ops += [
                Set("config", ("delegation", "provider"), ref(sub)),
                Set("config", ("delegation", "model"), sub.id),
            ]
        return Plan(ops=ops, warnings=warns)

    # ----------------------------------------------------------------- one-shot

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        d = target.default
        if d.protocol != "openai-completions":
            raise LaunchUnsupportedError(
                "Hermes can only be launched one-shot against an OpenAI-compatible "
                f"(chat completions) endpoint; '{d.id}' is served over {d.protocol}. "
                "Use `acm use` to configure it persistently."
            )
        warns = self._warnings(target)
        value = d.provider.credential.resolve(ctx.env)
        env_out = {"OPENAI_API_KEY": value} if value else {}
        argv = [
            launch.bin_path or "hermes", "chat", "--provider", "custom",
            "--base-url", d.base_url, "-m", d.id, *launch.passthrough,
        ]  # fmt: skip
        notes = [w.reason for w in warns]
        notes.append("auxiliary models and delegation keep the Hermes configuration for this run")
        return LaunchSpec(
            argv=argv, env=env_out, mode="exec", notes=notes,
            secret_env={"OPENAI_API_KEY"} if value else set(),
        )  # fmt: skip
