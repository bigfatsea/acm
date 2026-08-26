# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Core configuration data models and parser for ~/.acm/config.yaml (schema v3)."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from acm.errors import ConfigError

SupportedProtocol = Literal["openai", "anthropic", "openai-responses"]
SupportedEffort = Literal["low", "medium", "high"]
SupportedTools = Literal["native", "xml", "markdown"]


class ModelCapabilities(BaseModel):
    """Model feature capabilities."""

    model_config = ConfigDict(extra="forbid")

    vision: bool = False
    tools: SupportedTools = "native"
    json_mode: bool = False
    thinking: bool = False


class ModelReasoning(BaseModel):
    """Model reasoning/thinking configuration."""

    model_config = ConfigDict(extra="forbid")

    effort: SupportedEffort | None = None
    budget_tokens: int | None = Field(default=None, gt=0)


class ModelSpecConfig(BaseModel):
    """Configuration for a specific model specification (L2), embedded under a provider.

    Unlike v1's ModelConfig, this carries no `provider`/`id` fields: the provider is
    the enclosing `providers.<name>` mapping and the id is this entry's own key.
    """

    model_config = ConfigDict(extra="forbid")

    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    capabilities: ModelCapabilities | None = None
    reasoning: ModelReasoning | None = None


class ProviderConfig(BaseModel):
    """Configuration for an upstream LLM provider or router (L1), with embedded models (L2)."""

    model_config = ConfigDict(extra="forbid")

    protocol: SupportedProtocol
    base_url: str
    api_key: str
    headers: dict[str, str] = Field(default_factory=dict)
    proxy: str | None = None
    models: dict[str, ModelSpecConfig] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base_url has a valid HTTP/HTTPS scheme."""
        v_stripped = v.strip()
        if not v_stripped.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https:// (got: {v!r})")
        return v_stripped


class ProfileConfig(BaseModel):
    """Profile specification (L3): an optional registration set + optional default R3 ref.

    Registration (`models`) and selection (`default`) are orthogonal axes:
    - `models: {label: model-ref}` — the set to register into agent catalogs (Pi).
    - `default: model-ref` — the agent's default model. Resolved by the SAME R3 rules as a
      member value (bare id / qualified `provider.id`), NOT a member label.

    At least one of the two must be declared (V2); an empty profile has nothing to project.
    """

    model_config = ConfigDict(extra="forbid")

    models: dict[str, str] = Field(default_factory=dict)
    default: str | None = None


class CoreConfig(BaseModel):
    """Top-level Core Config representation for ~/.acm/config.yaml (schema v3)."""

    model_config = ConfigDict(extra="forbid")

    version: int = 3
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        """Validate configuration schema version (V6)."""
        if v != 3:
            raise ValueError(
                f"Unsupported config schema version: {v}. Expected version = 3. "
                "Please re-run 'acm init' or rewrite the file to version: 3."
            )
        return v

    @model_validator(mode="after")
    def validate_cross_references(self) -> "CoreConfig":
        """Validate referential integrity and reference resolution (V1-V5)."""
        if not self.profiles:
            raise ValueError("Configuration must define at least one profile under 'profiles'.")

        # V1: provider name / model id charset.
        for prov_name, prov_cfg in self.providers.items():
            if not prov_name.strip():
                raise ValueError("Provider name must be non-empty.")
            if prov_name != prov_name.strip():
                raise ValueError(
                    f"Provider name '{prov_name}' must not have leading/trailing whitespace."
                )
            if "." in prov_name:
                raise ValueError(
                    f"Provider name '{prov_name}' must not contain '.' "
                    "(reserved as the qualified-reference separator, e.g. 'provider.model-id')."
                )
            for model_key in prov_cfg.models:
                if not model_key.strip():
                    raise ValueError(f"Model id must be non-empty (in provider '{prov_name}').")

        for profile_name, profile_cfg in self.profiles.items():
            # V2: a profile must declare at least one of `models` (non-empty) or `default`.
            # Registration and selection are orthogonal; an empty profile has nothing to project.
            if not profile_cfg.models and profile_cfg.default is None:
                raise ValueError(
                    f"Profile '{profile_name}' must declare at least one of 'models' (non-empty) "
                    "or 'default'."
                )

            # V3 + V5: every member reference resolves (existence + non-ambiguity), and no
            # two members within the same profile collapse onto the same upstream model.
            seen_upstream: dict[tuple[str, str], str] = {}
            for label, ref in profile_cfg.models.items():
                if not label.strip():
                    raise ValueError(f"Profile '{profile_name}' member label must be non-empty.")
                prov_name, model_key = self._resolve_ref(profile_name, ref, subject=f"member '{label}'")

                upstream_key = (prov_name, model_key)
                if upstream_key in seen_upstream:
                    raise ValueError(
                        f"Profile '{profile_name}' members '{seen_upstream[upstream_key]}' and "
                        f"'{label}' both resolve to upstream model id '{model_key}' on provider "
                        f"'{prov_name}'; each member must resolve to a distinct upstream model "
                        "to avoid ambiguous entries in agent model selectors."
                    )
                seen_upstream[upstream_key] = label

            # V4: default (if present) is an R3 reference resolved by the SAME rules as a
            # member value (existence + non-ambiguity). It is NOT a member label.
            if profile_cfg.default is not None:
                self._resolve_ref(profile_name, profile_cfg.default, subject="default")

        return self

    def _resolve_ref(self, profile_name: str, ref: str, subject: str = "member") -> tuple[str, str]:
        """Resolve an R3 model reference to (provider_name, model_key).

        `subject` labels the referring context in error messages (e.g. "member 'coder'"
        for a `models:` value, "default" for the `default:` value).

        Full rules: docs/ACM_PROJECT_SPEC_v2.1.md §7.3.4.

        `<provider>.<id>` splits on the *first* dot (provider names may never contain a
        dot, so the split point is unambiguous even when the id itself contains dots).
        A bare `<id>` is looked up across every provider's models; zero matches is an
        unknown-model error, two or more is an ambiguity error listing all candidates.
        """
        if "." in ref:
            prov_name, model_key = ref.split(".", 1)
            if prov_name not in self.providers:
                raise ValueError(
                    f"Profile '{profile_name}' {subject}: provider '{prov_name}' "
                    f"(from qualified reference '{ref}') is not defined under 'providers'."
                )
            if model_key not in self.providers[prov_name].models:
                raise ValueError(
                    f"Profile '{profile_name}' {subject}: model id '{model_key}' is not "
                    f"defined under provider '{prov_name}'."
                )
            return prov_name, model_key

        candidates = sorted(
            prov_name for prov_name, prov_cfg in self.providers.items() if ref in prov_cfg.models
        )
        if not candidates:
            raise ValueError(
                f"Profile '{profile_name}' {subject}: unknown model id '{ref}'. "
                "It is not defined under any provider."
            )
        if len(candidates) > 1:
            raise ValueError(
                f"Profile '{profile_name}' {subject}: model id '{ref}' is ambiguous — "
                f"defined in providers: {candidates}. "
                f"Use a qualified reference like '{candidates[0]}.{ref}'."
            )
        return candidates[0], ref


def parse_config_yaml(content: str) -> CoreConfig:
    """Parse and validate YAML string content into CoreConfig.

    Loader contract:
    - YAML 1.2 semantics via the ruamel safe loader (no yes/no/on/off bool coercion)
    - duplicate keys are hard errors (fail-fast, never silently dropped)
    - anchors/merge keys are allowed and safely resolved
    - multi-document input is rejected
    """
    try:
        data = YAML(typ="safe").load(content)
    except YAMLError as e:
        raise ConfigError(f"Failed to parse YAML syntax: {e}") from e

    if data is None:
        raise ConfigError("Config file is empty or contains no YAML mapping.")
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config root must be a mapping (key: value structure), got {type(data).__name__}."
        )

    try:
        return CoreConfig.model_validate(data)
    except Exception as e:
        raise ConfigError(f"Invalid config structure: {e}") from e


def load_config(path: Path | str) -> CoreConfig:
    """Load and validate CoreConfig from a file path."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found at {p}. Run 'acm init' first.")
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        raise ConfigError(f"Failed to read config file {p}: {e}") from e

    return parse_config_yaml(content)
