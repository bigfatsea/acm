"""Pi and its parameter-only family members (OmO, Prime Agent). Support matrix §4.4 / §5."""

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
    display_name,
    groups,
    launch_notes,
    run_key_vars,
    secret_for_agent,
)
from acm.catalog.model import ResolvedModel, ResolvedTarget
from acm.core.context import Ctx
from acm.engine.model import FileSpec, Op, Plan, ProjectionWarning, Set
from acm.formats.base import KeyPath

_SETTINGS = ("defaultProvider", "defaultModel", "defaultThinkingLevel")
DUMMY_KEY = "dummy"  # Pi refuses a provider without an apiKey


@dataclass(frozen=True)
class PiMember:
    """Everything that differs between Pi and its forks: names and where they keep config."""

    id: str
    name: str
    tier: str
    aliases: tuple[str, ...]
    bins: tuple[str, ...]
    dir_env: tuple[str, ...]
    default_dir: str


PI = PiMember("pi", "Pi", "T1", (), ("pi",), ("PI_CODING_AGENT_DIR",), ".pi/agent")
OMO = PiMember(
    "omo", "OmO", "T2", ("omo-ai", "oh-my-openagent"), ("omo",),
    ("OMO_CODING_AGENT_DIR", "SENPI_CODING_AGENT_DIR"), ".omo/agent",
)  # fmt: skip
PRIME = PiMember(
    "prime_agent", "Prime Agent", "T2", ("prime", "prime-agent"), ("prime-agent",),
    ("PRIME_AGENT_CODING_AGENT_DIR",), ".prime/agent",
)  # fmt: skip


def model_entry(m: ResolvedModel, label: str | None = None) -> dict[str, Any]:
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


class PiFamily(Adapter):
    protocols = ("openai-completions", "anthropic-messages", "openai-responses")

    def __init__(self, member: PiMember = PI) -> None:
        self.member = member
        self.id = member.id
        self.name = member.name
        self.tier = member.tier  # type: ignore[assignment]
        self.aliases = member.aliases
        self.bins = member.bins

    def agent_dir(self, ctx: Ctx) -> Path:
        for var in self.member.dir_env:
            d = ctx.env.get(var, "").strip()
            if d and ctx.expand(d).is_absolute():
                return ctx.expand(d)
        return ctx.home / self.member.default_dir

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return [self.agent_dir(ctx)]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        d = self.agent_dir(ctx)
        return [
            FileSpec("models", d / "models.json", "json"),
            FileSpec("settings", d / "settings.json", "json"),
        ]

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical == "models":
            return len(path) == 2 and path[0] == "providers"
        return logical == "settings" and len(path) == 1 and path[0] in _SETTINGS

    # ------------------------------------------------------------------ helpers

    def _api_key(self, m: ResolvedModel, ctx: Ctx, warns: list[ProjectionWarning]) -> str:
        v = secret_for_agent(
            m.provider.credential, ctx, style="$NAME", agent=self.id, warnings=warns
        )
        return v or DUMMY_KEY

    def _provider_objects(
        self, target: ResolvedTarget, ctx: Ctx, warns: list[ProjectionWarning]
    ) -> dict[str, dict[str, Any]]:
        labels = {(m.provider.name, m.id, m.protocol): lab for lab, m in target.members.items()}
        out: dict[str, dict[str, Any]] = {}
        for (_pname, proto), models in groups(target).items():
            first = models[0]
            alias = alias_for(first.provider, proto)
            obj: dict[str, Any] = {
                "name": alias,
                "baseUrl": first.base_url,
                "api": proto,
                "apiKey": self._api_key(first, ctx, warns),
                "models": [
                    model_entry(m, labels.get((m.provider.name, m.id, m.protocol))) for m in models
                ],
            }
            if first.provider.headers:
                obj["headers"] = dict(first.provider.headers)
            out[alias] = obj
        return out

    def _collect_warnings(self, target: ResolvedTarget) -> list[ProjectionWarning]:
        warns = list(target.warnings)
        for role in ("subagent", "review"):
            if target.roles.get(role) is not None:
                warns.append(
                    ProjectionWarning(
                        f"roles.{role}", f"{self.name} has no slot for this role", self.id
                    )
                )
        return warns

    # --------------------------------------------------------------- persistent

    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan:
        d = target.default
        warns = self._collect_warnings(target)
        providers = self._provider_objects(target, ctx, warns)
        ops: list[Op] = [Set("models", ("providers", a), obj) for a, obj in providers.items()]
        ops.append(Set("settings", ("defaultProvider",), alias_for(d.provider, d.protocol)))
        ops.append(Set("settings", ("defaultModel",), d.id))
        if d.card.effort:
            ops.append(Set("settings", ("defaultThinkingLevel",), d.card.effort))
        return Plan(ops=ops, warnings=warns)

    # ----------------------------------------------------------------- one-shot

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        from importlib import resources

        from acm.adapters.base import LaunchUnsupportedError

        if self.tier != "T1":
            raise LaunchUnsupportedError(
                f"one-shot launch of {self.name} is disabled until its command-line flags are "
                "confirmed on a real install (a fork may rename them)"
            )
        d = target.default
        warns = self._collect_warnings(target)
        providers = self._provider_objects(target, ctx, warns)
        key_vars, env_out = run_key_vars(target, ctx)
        secret_env = set(env_out)
        for (pname, proto), models in groups(target).items():
            if pname in key_vars:
                providers[alias_for(models[0].provider, proto)]["apiKey"] = f"${key_vars[pname]}"
        listing = [{"alias": a, **obj} for a, obj in providers.items()]
        env_out["ACM_PI_PROVIDERS"] = json.dumps(listing, ensure_ascii=False, separators=(",", ":"))
        ext = str(resources.files("acm.adapters").joinpath("data/acm_pi_provider.ts"))
        argv = [
            launch.bin_path or self.bins[0],
            "-e",
            ext,
            "--model",
            f"{alias_for(d.provider, d.protocol)}/{d.id}",
        ]
        if d.card.effort:
            argv += ["--thinking", d.card.effort]
        argv += launch.passthrough
        return LaunchSpec(
            argv=argv, env=env_out, mode="exec", notes=launch_notes(warns),
            secret_env=secret_env,
        )  # fmt: skip
