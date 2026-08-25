# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Adapter types, contracts, and registry for ACM."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from acm.resolve import ResolvedProfile


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
    profile: ResolvedProfile,
    agent_id: str,
    supported_fields: set[str],
    pool_covered_model_ids: set[str] | None = None,
) -> list[ProjectionWarning]:
    """Emit ProjectionWarning for desired specifications unexpressible in the target agent.

    pool_covered_model_ids: model aliases already surfaced to the user via a
    model-pool aggregate warning elsewhere in plan(). A role whose target model
    is already covered is exempted here to avoid a redundant duplicate warning
    about the same underlying gap (see DESIGN_MODEL_POOL_v1.md §8.4).
    """
    covered = pool_covered_model_ids or set()
    warnings: list[ProjectionWarning] = []
    if profile.cheap and profile.cheap.model_id not in covered and "cheap" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="roles.cheap",
                agent_id=agent_id,
                reason=f"{agent_id} does not support secondary/cheap role slots in config",
            )
        )
    uncovered_extra_roles = {
        name: m for name, m in profile.extra_roles.items() if m.model_id not in covered
    }
    if uncovered_extra_roles and "extra_roles" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="roles.extra",
                agent_id=agent_id,
                reason=f"{agent_id} does not support custom role slots in config",
            )
        )
    if profile.main.temperature is not None and "temperature" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="temperature",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure temperature in config file",
            )
        )
    if profile.main.capabilities and "capabilities" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="capabilities",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure capabilities flags in config file",
            )
        )
    if profile.main.provider.headers and "headers" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="provider.headers",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure custom provider headers in config file",
            )
        )
    if profile.main.provider.proxy and "proxy" not in supported_fields:
        warnings.append(
            ProjectionWarning(
                field="provider.proxy",
                agent_id=agent_id,
                reason=f"{agent_id} does not configure provider proxy in config file",
            )
        )
    return warnings


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
