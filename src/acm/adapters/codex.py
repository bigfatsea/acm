# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Built-in adapter for Codex CLI (~/.codex/config.toml)."""

import shutil
from collections.abc import Mapping
from pathlib import Path

from acm.adapters import (
    PlannedOp,
    ProjectionWarning,
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
    """Compile ResolvedProfile into PlannedOps for Codex config.toml."""
    env_map = get_env_map(env)
    target_file = config_paths(env_map)[0]
    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    # 1. Top-level model & model_provider
    ops.append(PlannedOp(file=target_file, path="model", new=profile.main.upstream_id))
    ops.append(PlannedOp(file=target_file, path="model_provider", new=profile.main.provider.name))

    # 2. Reasoning effort
    if profile.main.reasoning and profile.main.reasoning.effort:
        ops.append(
            PlannedOp(
                file=target_file,
                path="model_reasoning_effort",
                new=profile.main.reasoning.effort,
            )
        )

    # 3. Model provider table
    prov = profile.main.provider
    prov_key = f"model_providers.{prov.name}"

    ops.append(
        PlannedOp(
            file=target_file,
            path=f"{prov_key}.name",
            new=prov.name,
        )
    )
    ops.append(
        PlannedOp(
            file=target_file,
            path=f"{prov_key}.base_url",
            new=prov.base_url,
        )
    )

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

    ops.append(
        PlannedOp(
            file=target_file,
            path=f"{prov_key}.wire_api",
            new=wire_api,
        )
    )

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

    ops.append(
        PlannedOp(
            file=target_file,
            path=f"{prov_key}.env_key",
            new=env_var_name,
        )
    )

    if profile.main.reasoning and profile.main.reasoning.budget_tokens:
        warnings.append(
            ProjectionWarning(
                field="reasoning.budget_tokens",
                agent_id=AGENT_ID,
                reason="Codex does not support custom budget_tokens in config.toml",
            )
        )

    if profile.main.context_window:
        warnings.append(
            ProjectionWarning(
                field="context_window",
                agent_id=AGENT_ID,
                reason="Codex does not configure context_window in config.toml",
            )
        )

    # Model pool: Codex has no pool channel — only main is ever projected.
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
            supported_fields={"main", "model_reasoning_effort"},
            pool_covered_model_ids=pool_covered_model_ids,
        )
    )

    return ops, warnings
