"""OpenCode and its parameter-only family members (MiMo Code, DevEco Code).

Support matrix §4.3 / §5. Config is JSONC: the format layer keeps the user's comments.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acm.adapters.base import (
    Adapter,
    DocView,
    LaunchContext,
    LaunchSpec,
    alias_for,
    anthropic_v1,
    display_name,
    groups,
    launch_notes,
    run_key_vars,
    secret_for_agent,
)
from acm.catalog.model import ResolvedModel, ResolvedTarget
from acm.core.context import Ctx
from acm.engine.model import Delete, FileSpec, Op, Plan, ProjectionWarning, Set
from acm.formats.base import KeyPath

NPM = {
    "openai-completions": "@ai-sdk/openai-compatible",
    "anthropic-messages": "@ai-sdk/anthropic",
    "openai-responses": "@ai-sdk/openai",
}
DEFAULT_OUTPUT = 32000  # OpenCode's schema needs limit.output whenever limit.context is given


@dataclass(frozen=True)
class OCMember:
    id: str
    name: str
    tier: str
    aliases: tuple[str, ...]
    bins: tuple[str, ...]
    stem: str  # config file stem: <stem>.jsonc / <stem>.json
    xdg_dir: str  # folder under $XDG_CONFIG_HOME
    dir_env: str | None  # env var that moves the whole config folder
    dir_env_subdir: str = ""  # sub-folder inside dir_env (MiMo: $MIMOCODE_HOME/config)


OPENCODE = OCMember(
    "opencode", "OpenCode", "T1", (), ("opencode",), "opencode", "opencode", "OPENCODE_CONFIG_DIR"
)
MIMO = OCMember(
    "mimocode", "MiMo Code", "T2", ("mimo",), ("mimo", "mimocode"), "mimocode", "mimocode",
    "MIMOCODE_HOME", "config",
)  # fmt: skip
DEVECO = OCMember(
    "deveco", "DevEco Code", "T2", (), ("deveco",), "deveco", "deveco", "DEVECO_CONFIG_DIR"
)


def model_entry(
    m: ResolvedModel, warns: list[ProjectionWarning], agent: str, label: str | None
) -> dict[str, Any]:
    c = m.card
    e: dict[str, Any] = {"name": display_name(m, label)}
    if c.reasoning:
        e["reasoning"] = True
    if c.tool_call:
        e["tool_call"] = True
    if "image" in c.input:
        e["modalities"] = {"input": ["text", "image"], "output": ["text"]}
        e["attachment"] = True
    ctxw = c.effective_context
    if ctxw:
        out = c.output
        if not out:
            out = min(DEFAULT_OUTPUT, ctxw)
            warns.append(
                ProjectionWarning(
                    f"models.{m.id}.limit.output",
                    f"unknown; wrote {out} because OpenCode requires it next to limit.context",
                    agent,
                )
            )
        e["limit"] = {"context": ctxw, "output": out}
    return e


class OpenCodeFamily(Adapter):
    protocols = ("openai-completions", "anthropic-messages", "openai-responses")

    def __init__(self, member: OCMember = OPENCODE) -> None:
        self.member = member
        self.id = member.id
        self.name = member.name
        self.tier = member.tier  # type: ignore[assignment]
        self.aliases = member.aliases
        self.bins = member.bins

    def config_dir(self, ctx: Ctx) -> Path:
        m = self.member
        if m.dir_env:
            d = ctx.env.get(m.dir_env, "").strip()
            if d and ctx.expand(d).is_absolute():
                base = ctx.expand(d)
                return base / m.dir_env_subdir if m.dir_env_subdir else base
        xdg = ctx.env.get("XDG_CONFIG_HOME", "").strip()
        root = ctx.expand(xdg) if xdg else ctx.home / ".config"
        return root / m.xdg_dir

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return [self.config_dir(ctx)]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        d = self.config_dir(ctx)
        stem = self.member.stem
        for name in (f"{stem}.jsonc", f"{stem}.json", "config.json"):
            if (d / name).exists():
                return [FileSpec("config", d / name, "jsonc")]
        return [FileSpec("config", d / f"{stem}.json", "jsonc")]

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical != "config":
            return False
        if len(path) == 1:
            return path[0] in ("model", "small_model")
        return len(path) == 2 and path[0] == "provider"

    # ------------------------------------------------------------------ helpers

    def _ref(self, m: ResolvedModel) -> str:
        return f"{alias_for(m.provider, m.protocol)}/{m.id}"

    def _providers(
        self, target: ResolvedTarget, ctx: Ctx, warns: list[ProjectionWarning]
    ) -> dict[str, dict[str, Any]]:
        labels = {(m.provider.name, m.id, m.protocol): lab for lab, m in target.members.items()}
        out: dict[str, dict[str, Any]] = {}
        for (_pname, proto), models in groups(target).items():
            first = models[0]
            alias = alias_for(first.provider, proto)
            url = anthropic_v1(first.base_url) if proto == "anthropic-messages" else first.base_url
            options: dict[str, Any] = {"baseURL": url}
            key = secret_for_agent(
                first.provider.credential, ctx, style="{env:NAME}", agent=self.id, warnings=warns
            )
            if key:
                options["apiKey"] = key
            if first.provider.headers:
                options["headers"] = dict(first.provider.headers)
            out[alias] = {
                "npm": NPM[proto],
                "name": alias,
                "options": options,
                "models": {
                    m.id: model_entry(
                        m, warns, self.id, labels.get((m.provider.name, m.id, m.protocol))
                    )
                    for m in models
                },
            }
        return out

    def _warnings(self, target: ResolvedTarget) -> list[ProjectionWarning]:
        warns = list(target.warnings)
        for role in ("reasoning", "subagent", "review"):
            if target.roles.get(role) is not None:
                what = (
                    "registered and selectable in the model picker"
                    if role == "reasoning"
                    else "has no slot"
                )
                warns.append(ProjectionWarning(f"roles.{role}", f"{self.name} {what}", self.id))
        return warns

    # --------------------------------------------------------------- persistent

    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan:
        warns = self._warnings(target)
        providers = self._providers(target, ctx, warns)
        ops: list[Op] = [Set("config", ("provider", a), obj) for a, obj in providers.items()]
        ops.append(Set("config", ("model",), self._ref(target.default)))
        fast = target.roles.get("fast")
        ops.append(
            Set("config", ("small_model",), self._ref(fast))
            if fast
            else Delete("config", ("small_model",))
        )
        return Plan(ops=ops, warnings=warns)

    # ----------------------------------------------------------------- one-shot

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        if self.member.tier != "T1":
            from acm.adapters.base import LaunchUnsupportedError

            raise LaunchUnsupportedError(
                f"one-shot launch of {self.name} is disabled until its inline-config variable is "
                "confirmed on a real install (it may differ from OpenCode's)"
            )
        warns = self._warnings(target)
        providers = self._providers(target, ctx, warns)
        key_vars, env_out = run_key_vars(target, ctx)
        secret_env = set(env_out)
        for (pname, proto), models in groups(target).items():
            if pname in key_vars:
                alias = alias_for(models[0].provider, proto)
                providers[alias]["options"]["apiKey"] = f"{{env:{key_vars[pname]}}}"
        content: dict[str, Any] = {"provider": providers, "model": self._ref(target.default)}
        fast = target.roles.get("fast")
        if fast:
            content["small_model"] = self._ref(fast)
        env_out["OPENCODE_CONFIG_CONTENT"] = json.dumps(
            content, ensure_ascii=False, separators=(",", ":")
        )
        argv = [launch.bin_path or self.bins[0], *launch.passthrough]
        return LaunchSpec(
            argv=argv, env=env_out, mode="exec", notes=launch_notes(warns),
            secret_env=secret_env,
        )  # fmt: skip
