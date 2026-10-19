"""Claude Code (``~/.claude/settings.json``). Rules: support matrix §4.1 / §7."""

import json
from pathlib import Path

from acm.adapters.base import Adapter, DocView, LaunchContext, LaunchSpec, printenv_command
from acm.catalog.model import ResolvedModel, ResolvedTarget
from acm.core.context import Ctx
from acm.engine.model import Delete, FileSpec, Op, Plan, ProjectionWarning, Set
from acm.formats.base import KeyPath

_ENV_SLOTS = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
)
_TOP = ("model", "effortLevel", "apiKeyHelper")
KEYLESS_PLACEHOLDER = "acm-no-key"


def _env(key: str, value: str) -> Set:
    return Set("settings", ("env", key), value)


class ClaudeCode(Adapter):
    id = "claude_code"
    name = "Claude Code"
    aliases = ("claude", "claude-code")
    bins = ("claude",)
    protocols = ("anthropic-messages",)

    def config_dir(self, ctx: Ctx) -> Path:
        d = ctx.env.get("CLAUDE_CONFIG_DIR")
        return ctx.expand(d) if d else ctx.home / ".claude"

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return [self.config_dir(ctx)]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        return [FileSpec("settings", self.config_dir(ctx) / "settings.json", "json")]

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical != "settings":
            return False
        if len(path) == 1:
            return path[0] in _TOP
        return len(path) == 2 and path[0] == "env" and path[1] in _ENV_SLOTS

    # ------------------------------------------------------------ shared mapping

    def _slots(self, target: ResolvedTarget) -> tuple[dict[str, str], list[ProjectionWarning]]:
        """env slot -> model id, with fallbacks to the default model when a role is missing."""
        warns: list[ProjectionWarning] = []
        d = target.default

        def pick(role: str, fallback: bool = True) -> str | None:
            m = target.roles.get(role)
            if m is not None:
                return m.id
            if fallback:
                warns.append(
                    ProjectionWarning(
                        f"roles.{role}",
                        f"no '{role}' model resolved; the matching slot uses the default model",
                        self.id,
                    )
                )
                return d.id
            return None

        reasoning = pick("reasoning")
        fast = pick("fast")
        slots = {
            "ANTHROPIC_DEFAULT_SONNET_MODEL": d.id,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": reasoning or d.id,
            "ANTHROPIC_DEFAULT_FABLE_MODEL": reasoning or d.id,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": fast or d.id,
        }
        sub = pick("subagent", fallback=False)
        if sub:
            slots["CLAUDE_CODE_SUBAGENT_MODEL"] = sub
        if target.roles.get("review") is not None:
            warns.append(
                ProjectionWarning(
                    "roles.review", "Claude Code has no separate review model", self.id
                )
            )
        return slots, warns

    def _context(self, d: ResolvedModel) -> int | None:
        return d.card.effective_context

    # ------------------------------------------------------------ persistent

    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan:
        d = target.default
        slots, warns = self._slots(target)
        warns = [*target.warnings, *warns]
        cred = d.provider.credential
        ops: list[Op] = [Set("settings", ("model",), d.id)]
        ops.append(_env("ANTHROPIC_BASE_URL", d.base_url))
        ops.extend(_env(k, v) for k, v in slots.items())
        value = cred.resolve(ctx.env)  # hard error before any write when a variable is unset
        if cred.is_reference and ctx.env.get(cred.var or "", "") != "":
            ops.append(Set("settings", ("apiKeyHelper",), printenv_command(cred)))
            ops.append(Delete("settings", ("env", "ANTHROPIC_AUTH_TOKEN")))
        elif value:
            warns.append(
                ProjectionWarning(
                    "api_key",
                    "written in plain text (config.yaml holds a literal); use ${VAR} to avoid that",
                    self.id,
                )
            )
            ops.append(_env("ANTHROPIC_AUTH_TOKEN", value))
            ops.append(Delete("settings", ("apiKeyHelper",)))
        else:
            ops.append(_env("ANTHROPIC_AUTH_TOKEN", KEYLESS_PLACEHOLDER))
            ops.append(Delete("settings", ("apiKeyHelper",)))
        # a real Anthropic key left in settings would be sent to the gateway
        ops.append(Delete("settings", ("env", "ANTHROPIC_API_KEY")))
        ctxw = self._context(d)
        if ctxw:
            ops.append(_env("CLAUDE_CODE_MAX_CONTEXT_TOKENS", str(ctxw)))
        if d.card.effort:
            ops.append(Set("settings", ("effortLevel",), d.card.effort))
        return Plan(ops=ops, warnings=warns)

    # ------------------------------------------------------------ one-shot

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        d = target.default
        slots, warns = self._slots(target)
        cred = d.provider.credential
        value = cred.resolve(ctx.env)
        env_out: dict[str, str] = {}
        secret_env: set[str] = set()
        settings: dict[str, object] = {"model": d.id}
        envblock: dict[str, str] = {
            "ANTHROPIC_BASE_URL": d.base_url,
            **slots,
            # blank anything the user's own settings.json would otherwise send
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
        }
        if value:
            var = cred.var if cred.var and ctx.env.get(cred.var, "") != "" else "ACM_RUN_KEY"
            if var == "ACM_RUN_KEY":
                env_out[var] = value
                secret_env.add(var)
            settings["apiKeyHelper"] = f"printenv {var}"
        else:
            envblock["ANTHROPIC_AUTH_TOKEN"] = KEYLESS_PLACEHOLDER
        ctxw = self._context(d)
        if ctxw:
            envblock["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(ctxw)
        if d.card.effort:
            settings["effortLevel"] = d.card.effort
        settings["env"] = envblock
        argv = [
            launch.bin_path or "claude",
            "--settings",
            json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
            *launch.passthrough,
        ]
        notes = [w.reason for w in [*target.warnings, *warns]]
        return LaunchSpec(argv=argv, env=env_out, mode="exec", notes=notes, secret_env=secret_env)
