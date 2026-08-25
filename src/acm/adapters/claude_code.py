# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Built-in adapter for Claude Code (~/.claude/settings.json)."""

import shutil
from collections.abc import Mapping
from pathlib import Path

from acm.adapters import (
    PlannedOp,
    ProjectionWarning,
    check_unsupported_profile_specs,
)
from acm.resolve import ResolvedProfile
from acm.util import get_env_map, get_home, resolve_agent_path

AGENT_ID = "claude_code"
DISPLAY_NAME = "Claude Code"


def detect(env: Mapping[str, str] | None = None) -> bool:
    """Detect if Claude Code is installed on the host."""
    env_map = get_env_map(env)
    # Check if executable exists in PATH
    if shutil.which("claude", path=env_map.get("PATH")):
        return True
    # Check if ~/.claude directory exists
    claude_dir = get_home(env_map) / ".claude"
    return claude_dir.exists()


def config_paths(env: Mapping[str, str] | None = None) -> list[Path]:
    """Return managed configuration path (~/.claude/settings.json)."""
    return [resolve_agent_path(AGENT_ID, ".claude/settings.json", env)]


def managed_namespaces() -> list[str]:
    """Return dot-path whitelist namespaces managed by this adapter."""
    return [
        "model",
        "env.ANTHROPIC_BASE_URL",
        "env.ANTHROPIC_AUTH_TOKEN",
        "env.ANTHROPIC_API_KEY",
        "effortLevel",
    ]


def plan(
    profile: ResolvedProfile, env: Mapping[str, str] | None = None
) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
    """Compile ResolvedProfile into PlannedOps for Claude Code settings.json."""
    env_map = get_env_map(env)
    target_file = config_paths(env_map)[0]
    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    # 1. Main model mapping
    ops.append(PlannedOp(file=target_file, path="model", new=profile.main.upstream_id))

    # 2. Base URL mapping
    ops.append(
        PlannedOp(
            file=target_file,
            path="env.ANTHROPIC_BASE_URL",
            new=profile.main.provider.base_url,
        )
    )
    if profile.main.provider.protocol != "anthropic":
        warnings.append(
            ProjectionWarning(
                field="provider.protocol",
                agent_id=AGENT_ID,
                reason=f"Claude Code uses the Anthropic Messages protocol, but provider '{profile.main.provider.name}' specifies '{profile.main.provider.protocol}'. Please ensure the endpoint is Anthropic-compatible or proxied via VMR.",
            )
        )

    # 3. Auth Token mapping
    ops.append(
        PlannedOp(
            file=target_file,
            path="env.ANTHROPIC_AUTH_TOKEN",
            new=profile.main.provider.api_key,
        )
    )

    # 4. Reasoning effort mapping
    if profile.main.reasoning and profile.main.reasoning.effort:
        ops.append(
            PlannedOp(
                file=target_file,
                path="effortLevel",
                new=profile.main.reasoning.effort,
            )
        )

    # 5. Projection warnings for unsupported specs
    if profile.main.reasoning and profile.main.reasoning.budget_tokens:
        warnings.append(
            ProjectionWarning(
                field="reasoning.budget_tokens",
                agent_id=AGENT_ID,
                reason="Claude Code settings.json does not support custom budget_tokens",
            )
        )

    if profile.main.context_window:
        warnings.append(
            ProjectionWarning(
                field="context_window",
                agent_id=AGENT_ID,
                reason="Claude Code does not support explicit context_window in settings.json",
            )
        )

    # 6. Model pool: Claude Code has no pool channel — only main is ever projected.
    pool_covered_model_ids: set[str] = {m.model_id for m in profile.pool.values()}
    if profile.pool:
        # Skipped-members are compared by (provider, upstream id), not bare id:
        # a pool member on a *different* provider with the same id string as
        # main is a distinct, unexpressed model and must still be listed
        # (DESIGN_MODEL_POOL_v1.md §16.1).
        skipped = [
            f"{lbl}({m.upstream_id})"
            for lbl, m in profile.pool.items()
            if (m.provider.name, m.upstream_id)
            != (profile.main.provider.name, profile.main.upstream_id)
        ]
        if skipped:
            warnings.append(
                ProjectionWarning(
                    field="pool",
                    agent_id=AGENT_ID,
                    reason=f"{DISPLAY_NAME} has no model-pool configuration channel; "
                    f"skipped pool members: {', '.join(skipped)}. Only main is projected.",
                )
            )

    warnings.extend(
        check_unsupported_profile_specs(
            profile,
            AGENT_ID,
            supported_fields={"main", "effortLevel"},
            pool_covered_model_ids=pool_covered_model_ids,
        )
    )

    return ops, warnings
