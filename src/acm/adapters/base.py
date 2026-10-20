"""Adapter contract, launch types, and helpers shared by adapters."""

import re
import shlex
import shutil
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from acm.catalog.model import Provider, ResolvedModel, ResolvedTarget
from acm.config.refs import CredentialRef
from acm.core.context import Ctx
from acm.core.errors import FormatError
from acm.engine.fsio import read_bytes
from acm.engine.model import AdapterLike, FileSpec, Plan, ProjectionWarning
from acm.formats.base import MISSING, Document, KeyPath, empty, parse

RUN_DIR_TOKEN = "@@RUN_DIR@@"


class DocView:
    """Read-only access to the agent's current files, for adapters that need to look."""

    def __init__(self, ctx: Ctx, specs: list[FileSpec]) -> None:
        self._specs = {s.logical: s for s in specs}
        self._docs: dict[str, Document | None] = {}

    def _doc(self, logical: str) -> Document | None:
        if logical not in self._docs:
            spec = self._specs[logical]
            data = read_bytes(spec.path)
            self._docs[logical] = parse(spec.format, data) if data is not None else None
        return self._docs[logical]

    def exists(self, logical: str) -> bool:
        return self._doc(logical) is not None

    def get(self, logical: str, path: KeyPath) -> Any:
        try:
            doc = self._doc(logical)
        except FormatError:
            return MISSING
        return MISSING if doc is None else doc.get(path)

    def doc_or_empty(self, logical: str) -> Document:
        doc = self._doc(logical)
        return doc if doc is not None else empty(self._specs[logical].format)


@dataclass
class LaunchContext:
    passthrough: list[str] = field(default_factory=list)
    bin_path: str | None = None
    model_override: bool = False  # `acm run -m`: the user picked the model explicitly


@dataclass
class LaunchSpec:
    """How to start the agent one-shot. Secrets must never appear in ``argv``."""

    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    tmp_files: dict[str, bytes] = field(default_factory=dict)  # name -> content, in the run dir
    mode: Literal["exec", "child"] = "exec"
    notes: list[str] = field(default_factory=list)
    secret_env: set[str] = field(default_factory=set)  # env names carrying secrets (masked)


class LaunchUnsupportedError(Exception):
    """This agent/target cannot be launched one-shot (message is shown to the user)."""


class Adapter(AdapterLike, ABC):
    id: str
    name: str
    tier: Literal["T1", "T2"] = "T1"
    aliases: tuple[str, ...] = ()
    bins: tuple[str, ...] = ()
    protocols: tuple[str, ...] = ()
    launch_supported: bool = True
    launch_note: str = ""

    # ---- discovery
    def detect(self, ctx: Ctx) -> bool:
        if any(shutil.which(b, path=ctx.env.get("PATH")) for b in self.bins):
            return True
        return any(d.exists() for d in self.detect_dirs(ctx))

    def detect_dirs(self, ctx: Ctx) -> list[Path]:
        return []

    def find_bin(self, ctx: Ctx) -> str | None:
        for b in self.bins:
            hit = shutil.which(b, path=ctx.env.get("PATH"))
            if hit:
                return hit
        return None

    @abstractmethod
    def files(self, ctx: Ctx) -> list[FileSpec]: ...

    @abstractmethod
    def is_managed(self, logical: str, path: KeyPath) -> bool: ...

    @abstractmethod
    def plan_files(self, target: ResolvedTarget, ctx: Ctx, view: DocView) -> Plan: ...

    def plan_launch(self, target: ResolvedTarget, ctx: Ctx, launch: LaunchContext) -> LaunchSpec:
        raise LaunchUnsupportedError(self.launch_note or f"{self.name} cannot be launched by acm")

    def matches(self, name: str) -> bool:
        n = name.lower().replace("-", "_")
        return n == self.id or n in {a.lower().replace("-", "_") for a in self.aliases}


# ---------------------------------------------------------------- helpers

_SUFFIX = {
    "openai-completions": "",
    "anthropic-messages": "-anthropic",
    "openai-responses": "-responses",
}


def alias_for(provider: Provider, protocol: str) -> str:
    """Name under which a provider is registered in an agent for one protocol.

    The provider's primary protocol keeps the plain name; others get a suffix.
    """
    if protocol == provider.primary_protocol:
        return provider.name
    return provider.name + _SUFFIX[protocol]


def groups(target: ResolvedTarget) -> dict[tuple[str, str], list[ResolvedModel]]:
    """Models to register, grouped by (provider name, protocol), in stable order."""
    out: dict[tuple[str, str], list[ResolvedModel]] = {}
    for m in target.all_models():
        out.setdefault((m.provider.name, m.protocol), []).append(m)
    return out


def display_name(m: ResolvedModel, label: str | None = None) -> str:
    return label or m.card.display_name or m.id


def anthropic_v1(url: str) -> str:
    """OpenCode's Anthropic SDK expects the base URL to end with /v1."""
    return url if url.rstrip("/").endswith("/v1") else url.rstrip("/") + "/v1"


def secret_for_agent(
    cred: CredentialRef, ctx: Ctx, *, style: str, agent: str, warnings: list[ProjectionWarning]
) -> str:
    """Render a credential in an agent's native syntax, falling back to the resolved value.

    ``style``: ``"$NAME"`` (Pi), ``"{env:NAME}"`` (OpenCode), ``"${NAME}"`` (OpenClaw, Hermes).
    A reference whose variable is unset but has a default is written as the default's value;
    an unset reference without a default is a hard error raised by ``cred.resolve``.
    """
    value = cred.resolve(ctx.env)  # ConfigError before anything is written
    if cred.var is not None and ctx.env.get(cred.var, "") != "":
        return {
            "$NAME": f"${cred.var}",
            "{env:NAME}": f"{{env:{cred.var}}}",
            "${NAME}": f"${{{cred.var}}}",
        }[style]
    if cred.var is not None:
        return value  # the default (possibly empty)
    if value:
        warnings.append(
            ProjectionWarning(
                "api_key",
                "the key is written in plain text because config.yaml holds it as a literal; "
                "use a ${VAR} reference to keep it out of the agent's file",
                agent,
            )
        )
    return value


def printenv_command(cred: CredentialRef) -> str:
    """Shell command that prints the credential from the environment (for apiKeyHelper)."""
    assert cred.var is not None
    cmd = f"printenv {cred.var}"
    if cred.default:
        cmd += f" || printf %s {shlex.quote(cred.default)}"
    return cmd


def env_mapping(ctx: Ctx) -> Mapping[str, str]:
    return ctx.env


def run_key_vars(target: ResolvedTarget, ctx: Ctx) -> tuple[dict[str, str], dict[str, str]]:
    """Environment variables carrying literal keys for a one-shot run, one per provider.

    Returns (provider name -> variable, variable -> key). The default model's provider uses
    ``ACM_RUN_KEY``; any other provider gets ``ACM_RUN_KEY_<NAME>``, so each key is only
    ever sent to its own endpoint. A provider whose key is a set ``${VAR}`` is left out: the
    agent's native reference to that variable is used instead.
    """
    names: dict[str, str] = {}
    env: dict[str, str] = {}
    seen: set[str] = set()
    for m in [target.default, *target.all_models()]:
        p = m.provider
        if p.name in seen:
            continue
        seen.add(p.name)
        cred = p.credential
        if cred.is_reference and ctx.env.get(cred.var or "", "") != "":
            continue
        value = cred.resolve(ctx.env)
        if not value:
            continue
        var = "ACM_RUN_KEY" if not names else "ACM_RUN_KEY_" + re.sub(
            r"[^A-Za-z0-9]", "_", p.name
        ).upper()
        names[p.name] = var
        env[var] = value
    return names, env


def launch_notes(warnings: list[ProjectionWarning]) -> list[str]:
    """Warnings worth showing for a one-shot run. "Key written in plain text" does not apply:
    a run passes literal keys through environment variables and writes no agent file."""
    return [f"{w.field}: {w.reason}" for w in warnings if w.field != "api_key"]
