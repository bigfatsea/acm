"""Codex CLI (``~/.codex/config.toml`` + an ACM-owned model catalog). Support matrix §4.2 / §7."""

import json
from importlib import resources
from pathlib import Path

import tomlkit

from acm.adapters.base import (
    RUN_DIR_TOKEN,
    Adapter,
    DocView,
    LaunchContext,
    LaunchSpec,
    alias_for,
)
from acm.catalog.model import ResolvedModel, ResolvedTarget
from acm.core.context import Ctx
from acm.engine.model import Delete, FileSpec, Op, OwnedFile, Plan, ProjectionWarning, Set
from acm.formats.base import KeyPath

_TOP = (
    "model", "model_provider", "model_reasoning_effort", "review_model", "model_catalog_json",
)  # fmt: skip
_LEVELS = (
    ("low", "Fast responses with lighter reasoning"),
    ("medium", "Balances speed and reasoning depth"),
    ("high", "Greater reasoning depth for complex problems"),
)


def base_instructions() -> str:
    return (
        resources.files("acm.adapters").joinpath("data/codex_base_instructions.md")
        .read_text(encoding="utf-8")
    )  # fmt: skip


def catalog_entry(m: ResolvedModel, priority: int) -> dict[str, object]:
    """A Codex ``ModelInfo`` for a gateway model (fields per codex-rs/protocol openai_models.rs).

    Everything not known about the model keeps the values Codex's own unknown-model fallback
    uses, except the window, reasoning levels and input modalities, which come from the card.
    """
    window = m.card.effective_context
    reasoning = bool(m.card.reasoning) or m.card.effort is not None
    entry: dict[str, object] = {
        "slug": m.id,
        "display_name": m.card.display_name or m.id,
        "description": m.card.description,
        "default_reasoning_level": (m.card.effort or "medium") if reasoning else None,
        "supported_reasoning_levels": (
            [{"effort": e, "description": d} for e, d in _LEVELS] if reasoning else []
        ),
        "shell_type": "unified_exec",
        "visibility": "list",
        "supported_in_api": True,
        "priority": priority,
        "availability_nux": None,
        "upgrade": None,
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "experimental_supported_tools": [],
        "input_modalities": [i for i in m.card.input if i in ("text", "image", "audio")],
        "base_instructions": base_instructions(),
    }
    if window:
        entry["context_window"] = window
        entry["max_context_window"] = window
    return entry


def toml_literal(value: object) -> str:
    """A TOML value for ``-c key=value`` (dicts become inline tables)."""

    def conv(v: object) -> object:
        if isinstance(v, dict):
            t = tomlkit.inline_table()
            for k, x in v.items():
                t[k] = conv(x)
            return t
        return v

    return str(tomlkit.item(conv(value)).as_string())


class Codex(Adapter):
    id = "codex"
    name = "Codex CLI"
    aliases = ("codex-cli",)
    bins = ("codex",)
    protocols = ("openai-responses",)

    def home(self, ctx: Ctx) -> Path:
        d = ctx.env.get("CODEX_HOME")
        return ctx.expand(d) if d else ctx.home / ".codex"

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return [self.home(ctx)]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        return [
            FileSpec("config", self.home(ctx) / "config.toml", "toml"),
            FileSpec("catalog", ctx.acm_home / "owned" / "codex" / "catalog.json", "json", True),
        ]

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical != "config":
            return False
        if len(path) == 1:
            return path[0] in _TOP
        if path[0] == "model_providers":
            return len(path) == 2
        return path == ("agents", "default_subagent_model")

    # -------------------------------------------------------------- shared

    def _provider_table(
        self, m: ResolvedModel, ctx: Ctx, key_env: str | None = None
    ) -> tuple[dict[str, object], list[ProjectionWarning]]:
        warns: list[ProjectionWarning] = []
        p = m.provider
        cred = p.credential
        value = cred.resolve(ctx.env)
        table: dict[str, object] = {
            "name": p.name, "base_url": m.base_url, "wire_api": "responses",
        }  # fmt: skip
        if key_env:
            table["env_key"] = key_env
        elif cred.is_reference and ctx.env.get(cred.var or "", "") != "":
            table["env_key"] = cred.var
        elif value:
            table["experimental_bearer_token"] = value
            warns.append(
                ProjectionWarning(
                    "api_key",
                    "written in plain text (config.yaml holds a literal); use ${VAR} instead",
                    self.id,
                )
            )
        if p.headers:
            table["http_headers"] = dict(p.headers)
        return table, warns

    def _collect(
        self, target: ResolvedTarget
    ) -> tuple[list[ResolvedModel], dict[str, ResolvedModel | None], list[ProjectionWarning]]:
        """Models for the catalog and the review / subagent slots.

        Codex sends every model through the one ``model_provider``, so models of any other
        provider are left out (with a warning) instead of being routed to the wrong endpoint.
        """
        warns = list(target.warnings)
        home = target.default.provider.name

        def usable(m: ResolvedModel, what: str) -> bool:
            if m.provider.name == home:
                return True
            warns.append(
                ProjectionWarning(
                    what,
                    f"'{m.id}' comes from provider '{m.provider.name}', but Codex sends every "
                    f"model to one provider ('{home}'); left out",
                    self.id,
                )
            )
            return False

        for role in ("reasoning", "fast"):
            if target.roles.get(role) is not None:
                warns.append(
                    ProjectionWarning(
                        f"roles.{role}",
                        "Codex has no dedicated slot for this role; the model is listed in /model",
                        self.id,
                    )
                )
        slots: dict[str, ResolvedModel | None] = {}
        for role in ("review", "subagent"):
            m = target.roles.get(role)
            slots[role] = m if m is not None and usable(m, f"roles.{role}") else None
        models = [m for m in target.all_models() if m.provider.name == home]
        for m in target.all_models():
            if m.provider.name != home and m not in (target.roles.get(r) for r in slots):
                usable(m, f"models.{m.id}")
        return models, slots, warns

    def _catalog_bytes(self, models: list[ResolvedModel]) -> bytes:
        entries = [catalog_entry(m, 10 + i) for i, m in enumerate(models)]
        return (json.dumps({"models": entries}, indent=2, ensure_ascii=False) + "\n").encode()

    # -------------------------------------------------------- persistent

    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan:
        d = target.default
        models, slots, warns = self._collect(target)
        table, w2 = self._provider_table(d, ctx)
        warns += w2
        alias = alias_for(d.provider, d.protocol)
        catalog_path = ctx.acm_home / "owned" / "codex" / "catalog.json"
        ops: list[Op] = [
            Set("config", ("model_provider",), alias),
            Set("config", ("model",), d.id),
            Set("config", ("model_providers", alias), table),
            Set("config", ("model_catalog_json",), str(catalog_path)),
            OwnedFile("catalog", self._catalog_bytes(models)),
        ]
        review = slots["review"]
        ops.append(
            Set("config", ("review_model",), review.id)
            if review
            else Delete("config", ("review_model",))
        )
        sub = slots["subagent"]
        ops.append(
            Set("config", ("agents", "default_subagent_model"), sub.id)
            if sub
            else Delete("config", ("agents", "default_subagent_model"))
        )
        if d.card.effort:
            ops.append(Set("config", ("model_reasoning_effort",), d.card.effort))
        return Plan(ops=ops, warnings=warns)

    # ----------------------------------------------------------- one-shot

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        d = target.default
        models, slots, warns = self._collect(target)
        cred = d.provider.credential
        value = cred.resolve(ctx.env)
        env_out: dict[str, str] = {}
        secret_env: set[str] = set()
        key_env: str | None = None
        if cred.is_reference and ctx.env.get(cred.var or "", "") != "":
            key_env = cred.var
        elif value:
            key_env = "ACM_RUN_KEY"
            env_out[key_env] = value
            secret_env.add(key_env)
        table, w2 = self._provider_table(d, ctx, key_env=key_env)
        alias = alias_for(d.provider, d.protocol)
        cfg = [
            ("model_provider", alias),
            ("model", d.id),
            (f"model_providers.{alias}", table),
            ("model_catalog_json", f"{RUN_DIR_TOKEN}/catalog.json"),
        ]
        if (review := slots["review"]) is not None:
            cfg.append(("review_model", review.id))
        if (sub := slots["subagent"]) is not None:
            cfg.append(("agents.default_subagent_model", sub.id))
        if d.card.effort:
            cfg.append(("model_reasoning_effort", d.card.effort))
        argv = [launch.bin_path or "codex"]
        for k, v in cfg:
            argv += ["-c", f"{k}={toml_literal(v)}"]
        argv += launch.passthrough
        return LaunchSpec(
            argv=argv,
            env=env_out,
            tmp_files={"catalog.json": self._catalog_bytes(models)},
            mode="child",
            notes=[w.reason for w in [*warns, *w2]],
            secret_env=secret_env,
        )
