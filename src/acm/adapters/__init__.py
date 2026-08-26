# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Adapter types, contracts, and registry for ACM."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from acm.resolve import ResolvedModel, ResolvedProfile


@dataclass(frozen=True)
class PlannedOp:
    """Pure desired state operation produced by an adapter plan() compilation."""

    file: Path
    path: str
    new: Any


@dataclass(frozen=True)
class FieldOp:
    """Full field operation enriched with disk reality by the Safety Engine."""

    file: Path
    path: str
    old: Any
    new: Any
    created: bool


class ProjectionWarning(BaseModel):
    """Warning emitted when a desired feature cannot be expressed by a target agent."""

    model_config = ConfigDict(extra="forbid")

    field: str
    agent_id: str
    reason: str


def check_unsupported_profile_specs(
    member: ResolvedModel | None,
    agent_id: str,
    supported_fields: set[str],
) -> list[ProjectionWarning]:
    """Emit ProjectionWarning for L2 specs on `member` unexpressible by the target agent.

    A single-member check (v1's cheap/extra_roles branches are gone along with the
    role concept itself — every profile member is now checked the same way, once each,
    by the adapter that owns it).
    """
    warnings: list[ProjectionWarning] = []
    if member is None:
        return warnings
    if member.temperature is not None and "temperature" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="temperature",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure temperature in config file",
            )
        )
    if member.capabilities and "capabilities" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="capabilities",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure capabilities flags in config file",
            )
        )
    if member.provider.headers and "headers" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="provider.headers",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure custom provider headers in config file",
            )
        )
    if member.provider.proxy and "proxy" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="provider.proxy",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure provider proxy in config file",
            )
        )
    return warnings


def _effective_default(profile: ResolvedProfile) -> tuple[str, ResolvedModel] | None:
    """Return (label, model) for the profile's opted-in default, or None if unset."""
    if profile.default_label is None:
        return None
    return profile.default_label, profile.models[profile.default_label]


def _unreachable_members(
    profile: ResolvedProfile, default_label: str
) -> list[tuple[str, ResolvedModel]]:
    """Members other than the connectivity provider's default.

    For single-default-slot agents (Claude Code, Codex): once a profile has opted in
    a default, every other member is unreachable for that agent (it has no pool
    channel). Compared by (provider, model_id), not label or bare id string: a member
    on a *different* provider that happens to share the default's upstream id string
    is still a distinct, unexpressed endpoint and must still be listed.
    """
    default_model = profile.models[default_label]
    default_key = (default_model.provider.name, default_model.model_id)
    return [
        (label, m)
        for label, m in profile.models.items()
        if (m.provider.name, m.model_id) != default_key
    ]


class AdapterProtocol(Protocol):
    """Contract specification for built-in agent adapters."""

    AGENT_ID: str
    DISPLAY_NAME: str

    def detect(self, env: Mapping[str, str] | None = None) -> bool:
        """Detect if this agent is installed on the host system."""
        ...

    def config_paths(self, env: Mapping[str, str] | None = None) -> list[Path]:
        """Return all config file paths managed by this adapter."""
        ...

    def managed_namespaces(self) -> list[str]:
        """Return whitelist dot-path namespaces managed by this adapter."""
        ...

    def plan(
        self, profile: ResolvedProfile, env: Mapping[str, str] | None = None
    ) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
        """Pure function: compile ResolvedProfile into desired ops and warnings."""
        ...


# Ordered built-in adapter registry list
ADAPTER_REGISTRY: list[Any] = []


def register_adapter(adapter: Any) -> None:
    """Register an adapter."""
    if adapter not in ADAPTER_REGISTRY:
        ADAPTER_REGISTRY.append(adapter)


def clear_adapters() -> None:
    """Clear registered adapters (useful for testing)."""
    ADAPTER_REGISTRY.clear()


def load_builtin_adapters() -> None:
    """Load and register all available built-in adapters."""
    import importlib

    for mod_name in ("claude_code", "codex", "pi"):
        try:
            mod = importlib.import_module(f"acm.adapters.{mod_name}")
            register_adapter(mod)
        except Exception as e:  # noqa: BLE001
            import sys

            sys.stderr.write(f"Warning: Failed to load built-in adapter '{mod_name}': {e}\n")


def get_adapters() -> list[Any]:
    """Get all registered adapters in deterministic order, initializing built-ins if empty."""
    if not ADAPTER_REGISTRY:
        load_builtin_adapters()
    return list(ADAPTER_REGISTRY)


def get_adapter_by_id(agent_id: str) -> Any | None:
    """Lookup adapter by AGENT_ID."""
    for adapter in get_adapters():
        if getattr(adapter, "AGENT_ID", None) == agent_id:
            return adapter
    return None
