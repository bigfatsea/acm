# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Projection engine: compiles ResolvedProfile into Desired State for each agent."""

from collections.abc import Mapping
from typing import Any

from acm.adapters import PlannedOp, ProjectionWarning
from acm.resolve import ResolvedProfile
from acm.util import get_env_map


def compute_desired_state(
    resolved_profile: ResolvedProfile,
    adapters: list[Any],
    env: Mapping[str, str] | None = None,
) -> dict[str, tuple[list[PlannedOp], list[ProjectionWarning]]]:
    """Compile desired state operations and projection warnings across registered adapters."""
    env_map = get_env_map(env)
    result: dict[str, tuple[list[PlannedOp], list[ProjectionWarning]]] = {}

    for adapter in adapters:
        ops, warnings = adapter.plan(resolved_profile, env_map)
        result[adapter.AGENT_ID] = (ops, warnings)

    return result
