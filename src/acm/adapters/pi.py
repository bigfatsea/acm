# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Built-in adapter for Pi Agent (~/.pi/agent/models.json and settings.json)."""

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from acm.adapters import (
    PlannedOp,
    ProjectionWarning,
    check_unsupported_profile_specs,
)
from acm.resolve import ResolvedProfile, extract_env_var_name
from acm.util import get_env_map, get_home, resolve_agent_path

AGENT_ID = "pi"
DISPLAY_NAME = "Pi Agent"


def detect(env: Mapping[str, str] | None = None) -> bool:
    """Detect if Pi Agent is installed on the host."""
    env_map = get_env_map(env)
    if shutil.which("pi", path=env_map.get("PATH")):
        return True
    pi_dir = get_home(env_map) / ".pi" / "agent"
    return pi_dir.exists()


def config_paths(env: Mapping[str, str] | None = None) -> list[Path]:
    """Return managed configuration paths (models.json, settings.json).

    Note: models-store.json is internal to Pi and strictly unmanaged.
    """
    return [
        resolve_agent_path(AGENT_ID, ".pi/agent/models.json", env),
        resolve_agent_path(AGENT_ID, ".pi/agent/settings.json", env),
    ]


def managed_namespaces() -> list[str]:
    """Return dot-path whitelist namespaces managed by this adapter."""
    return [
        "providers",
        "defaultProvider",
        "defaultModel",
        "defaultThinkingLevel",
    ]


def plan(
    profile: ResolvedProfile, env: Mapping[str, str] | None = None
) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
    """Compile ResolvedProfile into PlannedOps for Pi models.json and settings.json."""
    env_map = get_env_map(env)
    paths = config_paths(env_map)
    models_file, settings_file = paths[0], paths[1]

    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    # 1. Map provider into models.json
    prov = profile.main.provider
    api_dialect = (
        "anthropic-messages"
        if prov.protocol == "anthropic"
        else ("openai-responses" if prov.protocol == "openai-responses" else "openai-completions")
    )

    env_var_name = extract_env_var_name(prov.raw_api_key_ref)
    if env_var_name and env_var_name in env_map:
        api_key_val: str = f"${env_var_name}"
    elif prov.api_key:
        api_key_val = prov.api_key
    else:
        api_key_val = "dummy"
        warnings.append(
            ProjectionWarning(
                field="provider.api_key",
                agent_id=AGENT_ID,
                reason="Pi models.json requires non-empty apiKey; using 'dummy' for keyless provider.",
            )
        )

    model_entry: dict[str, Any] = {"id": profile.main.upstream_id}
    if profile.main.context_window:
        model_entry["contextWindow"] = profile.main.context_window
    if profile.main.max_output_tokens:
        model_entry["maxTokens"] = profile.main.max_output_tokens

    provider_payload: dict[str, Any] = {
        "baseUrl": prov.base_url,
        "api": api_dialect,
        "apiKey": api_key_val,
        "models": [model_entry],
    }

    ops.append(
        PlannedOp(
            file=models_file,
            path=f"providers.{prov.name}",
            new=provider_payload,
        )
    )

    # 2. Map default settings into settings.json
    ops.append(PlannedOp(file=settings_file, path="defaultProvider", new=prov.name))
    ops.append(PlannedOp(file=settings_file, path="defaultModel", new=profile.main.upstream_id))

    if profile.main.reasoning and profile.main.reasoning.effort:
        ops.append(
            PlannedOp(
                file=settings_file,
                path="defaultThinkingLevel",
                new=profile.main.reasoning.effort,
            )
        )

    if profile.main.reasoning and profile.main.reasoning.budget_tokens:
        warnings.append(
            ProjectionWarning(
                field="reasoning.budget_tokens",
                agent_id=AGENT_ID,
                reason="Pi settings.json does not support custom budget_tokens",
            )
        )

    warnings.extend(
        check_unsupported_profile_specs(
            profile,
            AGENT_ID,
            supported_fields={
                "main",
                "defaultThinkingLevel",
                "context_window",
                "max_output_tokens",
            },
        )
    )

    return ops, warnings
