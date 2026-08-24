# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Core configuration data models and parser for ~/.acm/config.toml."""

from pathlib import Path
from typing import Any, Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acm.errors import ConfigError

SupportedProtocol = Literal["openai", "anthropic", "openai-responses"]
SupportedEffort = Literal["low", "medium", "high"]
SupportedTools = Literal["native", "xml", "markdown"]


class ProviderConfig(BaseModel):
    """Configuration for an upstream LLM provider or router (L1)."""

    model_config = ConfigDict(extra="forbid")

    protocol: SupportedProtocol
    base_url: str
    api_key: str
    headers: dict[str, str] = Field(default_factory=dict)
    proxy: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base_url has a valid HTTP/HTTPS scheme."""
        v_stripped = v.strip()
        if not v_stripped.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https:// (got: {v!r})")
        return v_stripped


class ModelCapabilities(BaseModel):
    """Model feature capabilities."""

    model_config = ConfigDict(extra="forbid")

    vision: bool = False
    tools: SupportedTools = "native"
    json_mode: bool = False


class ModelReasoning(BaseModel):
    """Model reasoning/thinking configuration."""

    model_config = ConfigDict(extra="forbid")

    effort: SupportedEffort | None = None
    budget_tokens: int | None = Field(default=None, gt=0)


class ModelConfig(BaseModel):
    """Configuration for a specific model specification (L2)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    id: str
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    capabilities: ModelCapabilities | None = None
    reasoning: ModelReasoning | None = None


class ProfileConfig(BaseModel):
    """Profile specification binding roles to models (L3)."""

    model_config = ConfigDict(extra="allow")

    main: str
    cheap: str | None = None


class CoreConfig(BaseModel):
    """Top-level Core Config representation for ~/.acm/config.toml."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        """Validate configuration schema version."""
        if v != 1:
            raise ValueError(
                f"Unsupported config schema version: {v}. Expected version = 1. "
                "Please upgrade ACM or adjust version in ~/.acm/config.toml."
            )
        return v

    @model_validator(mode="after")
    def validate_cross_references(self) -> "CoreConfig":
        """Validate referential integrity between profiles, models, and providers."""
        if not self.profiles:
            raise ValueError("Configuration must define at least one profile under [profiles].")

        # Validate that each model references a defined provider
        for model_name, model_cfg in self.models.items():
            if model_cfg.provider not in self.providers:
                raise ValueError(
                    f"Model '{model_name}' references non-existent provider '{model_cfg.provider}'."
                )

        # Validate that each profile references defined models
        for profile_name, profile_cfg in self.profiles.items():
            if profile_cfg.main not in self.models:
                raise ValueError(
                    f"Profile '{profile_name}' main model '{profile_cfg.main}' is not defined under [models]."
                )
            if profile_cfg.cheap and profile_cfg.cheap not in self.models:
                raise ValueError(
                    f"Profile '{profile_name}' cheap model '{profile_cfg.cheap}' is not defined under [models]."
                )
            # Check any extra model role fields
            for extra_key, extra_val in (
                profile_cfg.__pydantic_extra__.items() if profile_cfg.__pydantic_extra__ else []
            ):
                if isinstance(extra_val, str) and extra_val not in self.models:
                    raise ValueError(
                        f"Profile '{profile_name}' role '{extra_key}' model '{extra_val}' is not defined under [models]."
                    )

        return self


def parse_config_toml(content: str) -> CoreConfig:
    """Parse and validate TOML string content into CoreConfig."""
    try:
        data: dict[str, Any] = dict(tomlkit.parse(content))
    except Exception as e:
        raise ConfigError(f"Failed to parse TOML syntax: {e}") from e

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

    return parse_config_toml(content)
