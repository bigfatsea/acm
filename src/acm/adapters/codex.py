# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Built-in adapter for Codex CLI (~/.codex/config.toml)."""

import shutil
from collections.abc import Mapping
from pathlib import Path

from acm.adapters import (
    PlannedOp,
    ProjectionWarning,
    _effective_default,
    _unreachable_members,
    check_unsupported_profile_specs,
)
from acm.resolve import ResolvedProfile, extract_env_var_name
from acm.util import get_env_map, get_home, resolve_agent_path

AGENT_ID = "codex"
DISPLAY_NAME = "Codex CLI"


def detect(env: Mapping[str, str] | None = None) -> bool:
    """Detect if Codex is installed on the host."""
    env_map = get_env_map(env)
    if shutil.which("codex", path=env_map.get("PATH")):
        return True
    codex_dir = get_home(env_map) / ".codex"
    return codex_dir.exists()


def config_paths(env: Mapping[str, str] | None = None) -> list[Path]:
    """Return managed configuration path (~/.codex/config.toml)."""
    return [resolve_agent_path(AGENT_ID, ".codex/config.toml", env)]


def managed_namespaces() -> list[str]:
    """Return dot-path whitelist namespaces managed by this adapter."""
    return [
        "model",
        "model_provider",
        "model_reasoning_effort",
        "model_providers",
    ]


def plan(
    profile: ResolvedProfile, env: Mapping[str, str] | None = None
) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
    """Compile ResolvedProfile into PlannedOps for Codex config.toml.

    Codex has no model-registry channel, so only the profile's opted-in `default`
    is ever projected. No `default` means nothing to project — a normal,
    explicitly-warned state, not an error.
    """
    env_map = get_env_map(env)
    target_file = config_paths(env_map)[0]
    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    default = _effective_default(profile)
    if default is None:
        warnings.append(
            ProjectionWarning(
                field="profile.default",
                agent_id=AGENT_ID,
                reason=f"{AGENT_ID} has no model-registry channel and the profile declares "
                "no 'default'; nothing to project for this agent.",
            )
        )
        return ops, warnings
    default_label, default_model = default

    # 1. Top-level model & model_provider
    ops.append(PlannedOp(file=target_file, path="model", new=default_model.model_id))
    ops.append(
        PlannedOp(file=target_file, path="model_provider", new=default_model.provider.name)
    )

    # 2. Reasoning effort
    if default_model.reasoning and default_model.reasoning.effort:
        ops.append(
            PlannedOp(
                file=target_file,
                path="model_reasoning_effort",
                new=default_model.reasoning.effort,
            )
        )

    # 3. Model provider table
    prov = default_model.provider
    prov_key = f"model_providers.{prov.name}"

    ops.append(PlannedOp(file=target_file, path=f"{prov_key}.name", new=prov.name))
    ops.append(PlannedOp(file=target_file, path=f"{prov_key}.base_url", new=prov.base_url))

    if prov.protocol in ("openai-responses", "openai"):
        wire_api = "responses"
    elif prov.protocol == "anthropic":
        wire_api = "chat"
        warnings.append(
            ProjectionWarning(
                field="provider.protocol",
                agent_id=AGENT_ID,
                reason=f"Codex CLI does not support dialect '{prov.protocol}' natively. Using 'chat'; please use an OpenAI-compatible endpoint or VMR.",
            )
        )
    else:
        wire_api = "responses"

    ops.append(PlannedOp(file=target_file, path=f"{prov_key}.wire_api", new=wire_api))

    env_var_name = extract_env_var_name(prov.raw_api_key_ref)
    if not env_var_name:
        warnings.append(
            ProjectionWarning(
                field="provider.api_key",
                agent_id=AGENT_ID,
                reason="Codex env_key requires an environment variable reference (e.g. '${VAR}'), but got plaintext. Using fallback 'OPENAI_API_KEY'; please ensure it is exported.",
            )
        )
        env_var_name = "OPENAI_API_KEY"

    ops.append(PlannedOp(file=target_file, path=f"{prov_key}.env_key", new=env_var_name))

    if default_model.reasoning and default_model.reasoning.budget_tokens:
        warnings.append(
            ProjectionWarning(
                field="reasoning.budget_tokens",
                agent_id=AGENT_ID,
                reason="Codex does not support custom budget_tokens in config.toml",
            )
        )

    if default_model.context_window:
        warnings.append(
            ProjectionWarning(
                field="context_window",
                agent_id=AGENT_ID,
                reason="Codex does not configure context_window in config.toml",
            )
        )

    # 4. Other members: Codex has no registry channel — only the default is ever
    # projected. Unreachable members are compared by (provider, model_id), not bare
    # id: a member on a *different* provider with the same id string as the default
    # is a distinct, unexpressed model and must still be listed.
    unreachable = _unreachable_members(profile, default_label)
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
            supported_fields={"model_reasoning_effort"},
        )
    )

    return ops, warnings
