# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Environment reference resolution and ResolvedProfile computation (schema v3)."""

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from acm.config import CoreConfig, ModelCapabilities, ModelReasoning
from acm.errors import ConfigError, NotFoundError
from acm.util import get_env_map

# Strict whole-field regex for credential reference: ${VAR} or ${VAR:-default}
ENV_REF_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}$")


def validate_credential_syntax(value: str) -> None:
    """Validate that credential references adhere strictly to whole-field ${VAR} / ${VAR:-default} syntax."""
    if ("${" in value or "}" in value) and not ENV_REF_PATTERN.match(value):
        raise ConfigError(
            f"Invalid credential reference syntax: {value!r}. "
            "ACM only supports strict whole-field '${VAR}' or '${VAR:-default}' syntax without substring interpolation or nesting."
        )


def extract_env_var_name(value: str) -> str | None:
    """If value is an ENV reference (${VAR} or ${VAR:-default}), return the variable name.

    Returns None if value is plaintext.
    """
    match = ENV_REF_PATTERN.match(value)
    if match:
        return match.group(1)
    return None


def evaluate_credential(value: str, env: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """Evaluate credential value in real-time.

    Returns:
        (resolved_value, missing_var_name | None)
    """
    validate_credential_syntax(value)
    match = ENV_REF_PATTERN.match(value)
    if not match:
        # Plaintext credential
        return value, None

    var_name = match.group(1)
    default_val = match.group(2)  # Can be None if no ':-' or '' if ':-'
    env_map = get_env_map(env)

    if var_name in env_map and env_map[var_name] != "":
        return env_map[var_name], None

    if default_val is not None:
        return default_val, None

    # Variable missing without default
    return "", var_name


class ResolvedProvider(BaseModel):
    """Fully resolved Provider with live credentials."""

    model_config = ConfigDict(extra="forbid")

    name: str
    protocol: str
    base_url: str
    api_key: str
    raw_api_key_ref: str
    headers: dict[str, str] = Field(default_factory=dict)
    proxy: str | None = None


class ResolvedModel(BaseModel):
    """Fully resolved Model specification.

    `model_id` is the upstream model id verbatim (the provider's `models.<id>` key) —
    v1's alias layer (a separate `model_id`/`upstream_id` pair) no longer exists in v2.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str
    provider: ResolvedProvider
    context_window: int | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    capabilities: ModelCapabilities | None = None
    reasoning: ModelReasoning | None = None


class ResolvedProfile(BaseModel):
    """Fully resolved Profile ready for adapter compilation.

    `models` is the registration set (label -> model); `default_model` is the
    independently-resolved default (an R3 ref, NOT a member label). Either may be
    empty/None independently — registration and selection are orthogonal.
    """

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    models: dict[str, ResolvedModel]
    default_model: ResolvedModel | None = None


def resolve_profile(
    profile_name: str,
    core_config: CoreConfig,
    env: Mapping[str, str] | None = None,
) -> ResolvedProfile:
    """Resolve a profile by name from CoreConfig against environment variables.

    Performs real-time credential resolution. If any required ENV variables are missing,
    aborts cleanly with ConfigError before any file writes can happen.
    """
    if profile_name not in core_config.profiles:
        available = ", ".join(sorted(core_config.profiles.keys()))
        raise NotFoundError(
            f"Profile '{profile_name}' not found. Available profiles: [{available}]"
        )

    profile_cfg = core_config.profiles[profile_name]
    env_map = get_env_map(env)
    missing_vars: set[str] = set()

    # Resolve every member's (provider, model_key) reference. Config-level validation
    # (V3) already guarantees these succeed for any CoreConfig built via parse_config_yaml;
    # this is defense-in-depth against a hand-constructed CoreConfig.
    member_refs: dict[str, tuple[str, str]] = {
        label: core_config._resolve_ref(profile_name, ref, subject=f"member '{label}'")
        for label, ref in profile_cfg.models.items()
    }

    # Resolve the default reference independently (same R3 rules, but it is NOT a member).
    default_ref: tuple[str, str] | None = None
    if profile_cfg.default is not None:
        default_ref = core_config._resolve_ref(
            profile_name, profile_cfg.default, subject="default"
        )

    reachable_provider_keys = {prov_name for prov_name, _ in member_refs.values()}
    if default_ref is not None:
        reachable_provider_keys.add(default_ref[0])

    resolved_providers: dict[str, ResolvedProvider] = {}
    for prov_name in reachable_provider_keys:
        prov_cfg = core_config.providers[prov_name]
        val, missing = evaluate_credential(prov_cfg.api_key, env_map)
        if missing:
            missing_vars.add(missing)
        resolved_providers[prov_name] = ResolvedProvider(
            name=prov_name,
            protocol=prov_cfg.protocol,
            base_url=prov_cfg.base_url,
            api_key=val,
            raw_api_key_ref=prov_cfg.api_key,
            headers=prov_cfg.headers,
            proxy=prov_cfg.proxy,
        )

    if missing_vars:
        missing_list = ", ".join(f"${{{v}}}" for v in sorted(missing_vars))
        raise ConfigError(
            f"Unresolved environment variables in configuration: {missing_list}. "
            "Please export them in your shell or define fallback defaults like '${VAR:-default}'."
        )

    def _resolve_model(prov_name: str, model_key: str) -> ResolvedModel:
        model_cfg = core_config.providers[prov_name].models[model_key]
        return ResolvedModel(
            model_id=model_key,
            provider=resolved_providers[prov_name],
            context_window=model_cfg.context_window,
            max_output_tokens=model_cfg.max_output_tokens,
            temperature=model_cfg.temperature,
            capabilities=model_cfg.capabilities,
            reasoning=model_cfg.reasoning,
        )

    # Declared order preserved (profile_cfg.models is an ordered dict from YAML).
    # No V5 re-check here: unlike v1 (whose implicit main-into-pool insertion could
    # create a collision invisible to config-time validation), v2 has no member
    # insertion mechanism at all — every member is explicit in `models:`, resolved
    # here via the *same* _resolve_ref() config.py's validator already ran. Any
    # CoreConfig that passed parse_config_yaml is therefore guaranteed collision-free
    # already; a second check here would just be dead code re-deriving the same result.
    models: dict[str, ResolvedModel] = {
        label: _resolve_model(*member_refs[label]) for label in profile_cfg.models
    }

    default_model: ResolvedModel | None = None
    if default_ref is not None:
        default_model = _resolve_model(*default_ref)

    return ResolvedProfile(
        profile_name=profile_name,
        models=models,
        default_model=default_model,
    )
