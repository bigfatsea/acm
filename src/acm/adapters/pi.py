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
    entry: dict[str, Any] = {"id": m.upstream_id, "name": label}
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
    is deliberately "ACM does not project" rather than "Pi does not support"
    (see DESIGN_MODEL_POOL_v1.md §16.2; same lesson as §13.8/§15 headers).
    capabilities.vision: projected into the model entry's `input` field
    (models.md) by _pi_model_entry — no warning.
    capabilities.tools (non-native dialect) / json_mode: no Pi channel at all.
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
    return warnings


def plan(
    profile: ResolvedProfile, env: Mapping[str, str] | None = None
) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
    """Compile ResolvedProfile into PlannedOps for Pi models.json and settings.json."""
    env_map = get_env_map(env)
    paths = config_paths(env_map)
    models_file, settings_file = paths[0], paths[1]

    ops: list[PlannedOp] = []
    warnings: list[ProjectionWarning] = []

    pool_covered_model_ids: set[str] = {m.model_id for m in profile.pool.values()}

    if profile.pool:
        # Group pool members by their provider (declared order preserved); each
        # provider gets one 'providers.<name>' op carrying its full models[] array.
        # Registration-only profiles (no main, DESIGN_MODEL_POOL_v1 §18) take this
        # path too, but skip the settings.json ops below (§18.2 R3).
        groups: dict[str, list[tuple[str, Any]]] = {}
        for label, m in profile.pool.items():
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

            # Pi's models.json has no 'proxy' concept (confirmed against the
            # official Provider Configuration field table — routing goes through
            # baseUrl instead), so a non-main pool provider's proxy setting is a
            # genuine, unavoidable projection loss and must stay explicit (§13.2).
            # headers *is* supported (projected above); no warning needed for it.
            if (
                profile.main is None or prov_name != profile.main.provider.name
            ) and group_prov.proxy:
                warnings.append(
                    ProjectionWarning(
                        field=f"pool.provider.{prov_name}.proxy",
                        agent_id=AGENT_ID,
                        reason=f"Pi models.json has no provider-level proxy field; pool "
                        f"provider '{prov_name}' proxy setting is not projected.",
                    )
                )

            for label, m in members:
                if profile.main is not None and m.model_id == profile.main.model_id:
                    continue
                if m.reasoning and (m.reasoning.effort or m.reasoning.budget_tokens):
                    warnings.append(
                        ProjectionWarning(
                            field=f"pool.{label}.reasoning",
                            agent_id=AGENT_ID,
                            reason="Pi does not support a per-model reasoning override in the "
                            "model pool; only main's defaultThinkingLevel is projected.",
                        )
                    )
                warnings.extend(_pi_member_unsupported_warnings(m, f"pool.{label}"))
    else:
        # 1. Map provider into models.json (single-model path, unchanged from pre-pool behavior)
        # Schema rule R1 (§18.2) guarantees main is declared when pool is absent.
        if profile.main is None:  # pragma: no cover - defensive, unreachable under schema
            return ops, warnings
        prov = profile.main.provider
        api_key_val, key_warnings = _resolve_pi_api_key(prov, env_map)
        warnings.extend(key_warnings)

        model_entry: dict[str, Any] = {"id": profile.main.upstream_id}
        if profile.main.context_window:
            model_entry["contextWindow"] = profile.main.context_window
        if profile.main.max_output_tokens:
            model_entry["maxTokens"] = profile.main.max_output_tokens
        if profile.main.capabilities and profile.main.capabilities.vision:
            model_entry["input"] = ["text", "image"]

        provider_payload: dict[str, Any] = {
            "baseUrl": prov.base_url,
            "api": _pi_api_dialect(prov.protocol),
            "apiKey": api_key_val,
            "models": [model_entry],
        }
        if prov.headers:
            provider_payload["headers"] = prov.headers

        ops.append(
            PlannedOp(
                file=models_file,
                path=f"providers.{prov.name}",
                new=provider_payload,
            )
        )

    # 2. Map default settings into settings.json (always driven by main, regardless of pool)
    if profile.main is None:
        # Registration-only profile (§18.2 R3): default-model fields stay
        # user-owned; surface that decision explicitly instead of silently
        # leaving settings.json untouched.
        warnings.append(
            ProjectionWarning(
                field="profile.main",
                agent_id=AGENT_ID,
                reason="Profile declares no 'main' (registration-only): ACM will not change "
                "defaultProvider/defaultModel/defaultThinkingLevel; the current defaults "
                "remain user-managed.",
            )
        )
        return ops, warnings

    ops.append(
        PlannedOp(file=settings_file, path="defaultProvider", new=profile.main.provider.name)
    )
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

    # Main member's temperature/capabilities: surfaced here with honest wording
    # (see _pi_member_unsupported_warnings); the shared check below is told
    # these fields are "supported" so its blanket, factually-wrong-for-Pi text
    # never fires (§16.2/§16.3).
    warnings.extend(_pi_member_unsupported_warnings(profile.main, ""))

    warnings.extend(
        check_unsupported_profile_specs(
            profile,
            AGENT_ID,
            supported_fields={
                "main",
                "defaultThinkingLevel",
                "context_window",
                "max_output_tokens",
                "headers",
                "temperature",
                "capabilities",
            },
            pool_covered_model_ids=pool_covered_model_ids,
        )
    )

    return ops, warnings
