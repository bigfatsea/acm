# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Built-in adapter for Claude Code (~/.claude/settings.json)."""

import shutil
from collections.abc import Mapping
from pathlib import Path

from acm.adapters import (
    PlannedOp,
    ProjectionWarning,
    _unreachable_members,
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
    """Compile ResolvedProfile into PlannedOps for Claude Code settings.json.

    Claude Code has no model-registry channel, so only the profile's opted-in
    `default` is ever projected. No `default` means nothing to project — a normal,
    explicitly-warned state, not an error.
    """
    env_map = get_env_map(env)
    target_file = config_paths(env_map)[0]
    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    default_model = profile.default_model
    if default_model is None:
        warnings.append(
            ProjectionWarning(
                field="profile.default",
                agent_id=AGENT_ID,
                reason=f"{AGENT_ID} has no model-registry channel and the profile declares "
                "no 'default'; nothing to project for this agent.",
            )
        )
        return ops, warnings

    # 1. Default model mapping
    ops.append(PlannedOp(file=target_file, path="model", new=default_model.model_id))

    # 2. Base URL mapping
    ops.append(
        PlannedOp(
            file=target_file,
            path="env.ANTHROPIC_BASE_URL",
            new=default_model.provider.base_url,
        )
    )
    if default_model.provider.protocol != "anthropic":
        warnings.append(
            ProjectionWarning(
                field="provider.protocol",
                agent_id=AGENT_ID,
                reason=f"Claude Code uses the Anthropic Messages protocol, but provider '{default_model.provider.name}' specifies '{default_model.provider.protocol}'. Please ensure the endpoint is Anthropic-compatible or proxied via VMR.",
            )
        )

    # 3. Auth Token mapping
    ops.append(
        PlannedOp(
            file=target_file,
            path="env.ANTHROPIC_AUTH_TOKEN",
            new=default_model.provider.api_key,
        )
    )

    # 4. Reasoning effort mapping
    if default_model.reasoning and default_model.reasoning.effort:
        ops.append(
            PlannedOp(
                file=target_file,
                path="effortLevel",
                new=default_model.reasoning.effort,
            )
        )

    # 5. Projection warnings for unsupported specs
    if default_model.reasoning and default_model.reasoning.budget_tokens:
        warnings.append(
            ProjectionWarning(
                field="reasoning.budget_tokens",
                agent_id=AGENT_ID,
                reason="Claude Code settings.json does not support custom budget_tokens",
            )
        )

    if default_model.context_window:
        warnings.append(
            ProjectionWarning(
                field="context_window",
                agent_id=AGENT_ID,
                reason="Claude Code does not support explicit context_window in settings.json",
            )
        )

    # 6. Other members: Claude Code has no registry channel — only the default is
    # ever projected. Unreachable members are compared by (provider, model_id), not
    # bare id: a member on a *different* provider with the same id string as the
    # default is a distinct, unexpressed model and must still be listed.
    unreachable = _unreachable_members(profile, default_model)
    if unreachable:
        skipped = [f"{lbl}({m.model_id})" for lbl, m in unreachable]
        warnings.append(
            ProjectionWarning(
                field="models.unreachable",
                agent_id=AGENT_ID,
                reason=f"{DISPLAY_NAME} has no model-registry configuration channel; "
                f"unreachable members: {', '.join(skipped)}. Only the default is projected.",
            )
        )

    warnings.extend(
        check_unsupported_profile_specs(
            default_model,
            AGENT_ID,
            supported_fields={"effortLevel"},
        )
    )

    return ops, warnings
