# // Ver 2026-08-26 00:00, by claude-sonnet-5
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


def _pi_api_dialect(protocol: str) -> str:
    """Map ACM protocol dialect to Pi's models.json 'api' field."""
    if protocol == "anthropic":
        return "anthropic-messages"
    if protocol == "openai-responses":
        return "openai-responses"
    return "openai-completions"


def _resolve_pi_api_key(
    prov: Any, env_map: Mapping[str, str]
) -> tuple[str, list[ProjectionWarning]]:
    """Resolve the apiKey value for a provider's Pi models.json entry."""
    warnings: list[ProjectionWarning] = []
    env_var_name = extract_env_var_name(prov.raw_api_key_ref)
    if env_var_name and env_var_name in env_map:
        return f"${env_var_name}", warnings
    if prov.api_key:
        return prov.api_key, warnings
    warnings.append(
        ProjectionWarning(
            field="provider.api_key",
            agent_id=AGENT_ID,
            reason="Pi models.json requires non-empty apiKey; using 'dummy' for keyless provider.",
        )
    )
    return "dummy", warnings


def _pi_model_entry(label: str, m: Any) -> dict[str, Any]:
    """Build a single Pi models.json model entry; label lands in 'name' (secondary detail text, not the primary /model picker label, which is driven by 'id')."""
    entry: dict[str, Any] = {"id": m.model_id, "name": label}
    if m.context_window:
        entry["contextWindow"] = m.context_window
    if m.max_output_tokens:
        entry["maxTokens"] = m.max_output_tokens
    if m.capabilities and m.capabilities.vision:
        entry["input"] = ["text", "image"]
    return entry


def _pi_member_unsupported_warnings(
    m: Any, field_prefix: str
) -> list[ProjectionWarning]:
    """Projection-loss warnings for L2 specs a Pi model entry cannot express.

    temperature: Pi *can* express per-model temperature via model-level
    `samplingParams` on OpenAI-compatible dialects (models.md) — ACM does not
    project it yet, so the value is still lost and must be surfaced. The wording
    is deliberately "ACM does not project" rather than "Pi does not support".
    capabilities.vision: projected into the model entry's `input` field
    (models.md) by _pi_model_entry — no warning.
    capabilities.tools (non-native dialect) / json_mode / thinking: no Pi channel at all.
    """
    warnings: list[ProjectionWarning] = []

    def _field(name: str) -> str:
        return f"{field_prefix}.{name}" if field_prefix else name

    if m.temperature is not None:
        warnings.append(
            ProjectionWarning(
                field=_field("temperature"),
                agent_id=AGENT_ID,
                reason="ACM does not project per-model temperature into Pi models.json; "
                "Pi can express it via model-level samplingParams on "
                "OpenAI-compatible dialects, but ACM does not write that yet.",
            )
        )
    if m.capabilities:
        if m.capabilities.tools != "native":
            warnings.append(
                ProjectionWarning(
                    field=_field("capabilities.tools"),
                    agent_id=AGENT_ID,
                    reason=f"Pi models.json has no tool-calling dialect field; "
                    f"capabilities.tools='{m.capabilities.tools}' is not projected.",
                )
            )
        if m.capabilities.json_mode:
            warnings.append(
                ProjectionWarning(
                    field=_field("capabilities.json_mode"),
                    agent_id=AGENT_ID,
                    reason="Pi models.json has no json-mode capability flag; "
                    "capabilities.json_mode is not projected.",
                )
            )
        if m.capabilities.thinking:
            warnings.append(
                ProjectionWarning(
                    field=_field("capabilities.thinking"),
                    agent_id=AGENT_ID,
                    reason="Pi models.json has no thinking-capability channel; "
                    "capabilities.thinking is not projected.",
                )
            )
    return warnings


def plan(
    profile: ResolvedProfile, env: Mapping[str, str] | None = None
) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
    """Compile ResolvedProfile into PlannedOps for Pi models.json and settings.json.

    Registration and selection are independent: every member is registered into
    models.json unconditionally; settings.json is only touched when the profile
    declares a `default` (Spec §2.3 — no default is a normal, non-warning state).
    """
    env_map = get_env_map(env)
    paths = config_paths(env_map)
    models_file, settings_file = paths[0], paths[1]

    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    default_label = profile.default_label
    default_model = profile.models[default_label] if default_label is not None else None
    default_provider_name = default_model.provider.name if default_model is not None else None

    # Group all members by provider (declared order preserved); each provider gets
    # one 'providers.<name>' op carrying its full models[] array.
    groups: dict[str, list[tuple[str, Any]]] = {}
    for label, m in profile.models.items():
        groups.setdefault(m.provider.name, []).append((label, m))

    for prov_name, members in groups.items():
        group_prov = members[0][1].provider
        api_key_val, key_warnings = _resolve_pi_api_key(group_prov, env_map)
        warnings.extend(key_warnings)

        models_arr = [_pi_model_entry(label, m) for label, m in members]
        group_payload: dict[str, Any] = {
            "baseUrl": group_prov.base_url,
            "api": _pi_api_dialect(group_prov.protocol),
            "apiKey": api_key_val,
            "models": models_arr,
        }
        if group_prov.headers:
            group_payload["headers"] = group_prov.headers
        ops.append(
            PlannedOp(
                file=models_file,
                path=f"providers.{prov_name}",
                new=group_payload,
            )
        )

        # Pi's models.json has no 'proxy' concept (confirmed against the official
        # Provider Configuration field table — routing goes through baseUrl instead),
        # so a non-default provider's proxy setting is a genuine, unavoidable
        # projection loss and must stay explicit. The default's own provider proxy
        # (if any) is instead surfaced via the shared check_unsupported_profile_specs
        # call below, to avoid a duplicate warning. headers *is* supported (projected
        # above); no warning needed for it.
        if prov_name != default_provider_name and group_prov.proxy:
            warnings.append(
                ProjectionWarning(
                    field=f"models.provider.{prov_name}.proxy",
                    agent_id=AGENT_ID,
                    reason=f"Pi models.json has no provider-level proxy field; provider "
                    f"'{prov_name}' proxy setting is not projected.",
                )
            )

        for label, m in members:
            if label == default_label:
                continue
            if m.reasoning and (m.reasoning.effort or m.reasoning.budget_tokens):
                reason = (
                    "Pi does not support a per-model reasoning override in the "
                    "model registry; only the default's defaultThinkingLevel is "
                    "projected."
                    if default_label is not None
                    else "Pi does not support a per-model reasoning override in the "
                    "model registry; this profile has no default, so no "
                    "defaultThinkingLevel is projected for any member."
                )
                warnings.append(
                    ProjectionWarning(
                        field=f"models.{label}.reasoning",
                        agent_id=AGENT_ID,
                        reason=reason,
                    )
                )
            warnings.extend(_pi_member_unsupported_warnings(m, f"models.{label}"))

    # settings.json is driven exclusively by the opted-in default. No default means
    # ACM never touches this file — a normal, non-warning state.
    if default_model is None:
        return ops, warnings

    ops.append(
        PlannedOp(file=settings_file, path="defaultProvider", new=default_model.provider.name)
    )
    ops.append(PlannedOp(file=settings_file, path="defaultModel", new=default_model.model_id))

    if default_model.reasoning and default_model.reasoning.effort:
        ops.append(
            PlannedOp(
                file=settings_file,
                path="defaultThinkingLevel",
                new=default_model.reasoning.effort,
            )
        )

    if default_model.reasoning and default_model.reasoning.budget_tokens:
        warnings.append(
            ProjectionWarning(
                field="reasoning.budget_tokens",
                agent_id=AGENT_ID,
                reason="Pi settings.json does not support custom budget_tokens",
            )
        )

    # Default member's temperature/capabilities: surfaced here with honest wording
    # (see _pi_member_unsupported_warnings); the shared check below is told these
    # fields are "supported" so its blanket, factually-wrong-for-Pi text never fires.
    warnings.extend(_pi_member_unsupported_warnings(default_model, ""))

    warnings.extend(
        check_unsupported_profile_specs(
            default_model,
            AGENT_ID,
            supported_fields={
                "defaultThinkingLevel",
                "context_window",
                "max_output_tokens",
                "headers",
                "temperature",
                "capabilities",
            },
        )
    )

    return ops, warnings
