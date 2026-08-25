# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Environment reference resolution and ResolvedProfile computation."""

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
    """Fully resolved Model specification."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    upstream_id: str
    provider: ResolvedProvider
    context_window: int | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    capabilities: ModelCapabilities | None = None
    reasoning: ModelReasoning | None = None


class ResolvedProfile(BaseModel):
    """Fully resolved Profile ready for adapter compilation."""

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    main: ResolvedModel
    cheap: ResolvedModel | None = None
    extra_roles: dict[str, ResolvedModel] = Field(default_factory=dict)
    pool: dict[str, ResolvedModel] = Field(default_factory=dict)


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

    # Collect models and providers reachable from this specific profile
    reachable_model_keys: set[str] = {profile_cfg.main}
    if profile_cfg.cheap:
        reachable_model_keys.add(profile_cfg.cheap)
    if profile_cfg.__pydantic_extra__:
        for role_val in profile_cfg.__pydantic_extra__.values():
            if isinstance(role_val, str) and role_val in core_config.models:
                reachable_model_keys.add(role_val)
    if profile_cfg.pool:
        reachable_model_keys.update(
            alias for alias in profile_cfg.pool.values() if alias in core_config.models
        )

    reachable_provider_keys = {
        core_config.models[m].provider for m in reachable_model_keys if m in core_config.models
    }

    # Resolve only reachable providers
    resolved_providers: dict[str, ResolvedProvider] = {}
    for prov_name in reachable_provider_keys:
        if prov_name in core_config.providers:
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

    def _resolve_model(model_key: str) -> ResolvedModel:
        model_cfg = core_config.models[model_key]
        provider = resolved_providers[model_cfg.provider]
        return ResolvedModel(
            model_id=model_key,
            upstream_id=model_cfg.id,
            provider=provider,
            context_window=model_cfg.context_window,
            max_output_tokens=model_cfg.max_output_tokens,
            temperature=model_cfg.temperature,
            capabilities=model_cfg.capabilities,
            reasoning=model_cfg.reasoning,
        )

    main_model = _resolve_model(profile_cfg.main)
    cheap_model = _resolve_model(profile_cfg.cheap) if profile_cfg.cheap else None

    extra_roles: dict[str, ResolvedModel] = {}
    if profile_cfg.__pydantic_extra__:
        for role_name, model_key in profile_cfg.__pydantic_extra__.items():
            if isinstance(model_key, str) and model_key in core_config.models:
                extra_roles[role_name] = _resolve_model(model_key)

    # Model pool: label -> ResolvedModel, in declared order; main is implicitly
    # ensured a member (prepended under label "main" if not already referenced).
    pool: dict[str, ResolvedModel] = {}
    if profile_cfg.pool:
        declared_pool = {label: _resolve_model(alias) for label, alias in profile_cfg.pool.items()}
        if not any(m.model_id == profile_cfg.main for m in declared_pool.values()):
            pool = {"main": main_model, **declared_pool}
        else:
            pool = declared_pool

        # config.py's cross-reference check only sees explicitly declared pool
        # entries; the implicitly-inserted main member (R2, above) can still
        # collide on upstream id with a distinct explicit alias, so re-check
        # the fully assembled pool here (defense-in-depth, not redundant).
        seen_upstream: dict[tuple[str, str], str] = {}
        for label, m in pool.items():
            key = (m.provider.name, m.upstream_id)
            if key in seen_upstream:
                raise ConfigError(
                    f"Profile '{profile_name}' pool labels '{seen_upstream[key]}' and '{label}' "
                    f"both resolve to upstream model id '{m.upstream_id}' on provider "
                    f"'{m.provider.name}'; each pool member must resolve to a distinct upstream "
                    "model to avoid ambiguous entries in agent model selectors."
                )
            seen_upstream[key] = label

    return ResolvedProfile(
        profile_name=profile_name,
        main=main_model,
        cheap=cheap_model,
        extra_roles=extra_roles,
        pool=pool,
    )
