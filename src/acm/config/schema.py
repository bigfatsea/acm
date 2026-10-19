"""Core configuration schema v4 (``~/.acm/config.yaml``)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acm.config.refs import (
    NON_DEFAULT_ROLES,
    PROVIDER_NAME,
    ROLES,
    ModelRef,
    RoleRef,
    parse_credential,
    parse_ref,
)
from acm.core.errors import ConfigError

Protocol = Literal["openai-completions", "anthropic-messages", "openai-responses"]
PROTOCOLS: tuple[str, ...] = ("openai-completions", "anthropic-messages", "openai-responses")
Effort = Literal["low", "medium", "high"]
InputKind = Literal["text", "image", "audio", "video"]
SCHEMA_VERSION = 4


class ModelSpec(BaseModel):
    """Static model metadata (L2)."""

    model_config = ConfigDict(extra="forbid")

    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    input: list[InputKind] = ["text"]
    tool_call: bool | None = None
    reasoning: bool | None = None
    effort: Effort | None = None
    roles: list[str] = Field(default_factory=list)

    @field_validator("roles")
    @classmethod
    def _roles_valid(cls, v: list[str]) -> list[str]:
        for r in v:
            if r not in ROLES:
                raise ValueError(f"unknown role {r!r} (valid: {', '.join(ROLES)})")
        return v


class ProviderConfig(BaseModel):
    """A provider (L1): static (protocol + base_url + models) or Manifest-backed."""

    model_config = ConfigDict(extra="forbid")

    protocol: Protocol | None = None
    base_url: str | None = None
    manifest: str | None = None
    api_key: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    models: dict[str, ModelSpec] = Field(default_factory=dict)

    @property
    def is_manifest(self) -> bool:
        return self.manifest is not None

    @field_validator("api_key")
    @classmethod
    def _api_key_syntax(cls, v: str) -> str:
        try:
            parse_credential(v)
        except ConfigError as e:
            raise ValueError(e.message) from e
        return v

    @model_validator(mode="after")
    def _shape(self) -> "ProviderConfig":
        if self.manifest is not None:
            if self.protocol or self.base_url or self.models:
                raise ValueError("a manifest provider cannot declare protocol, base_url or models")
            if not self.manifest.strip():
                raise ValueError("manifest must not be empty")
            return self
        if not self.protocol or not self.base_url:
            raise ValueError("a static provider needs protocol and base_url (or use manifest)")
        if not self.base_url.strip().startswith(("http://", "https://")):
            raise ValueError(
                f"base_url must start with http:// or https:// (got {self.base_url!r})"
            )
        if not self.models:
            raise ValueError("a static provider needs at least one model")
        self.base_url = self.base_url.strip().rstrip("/")
        return self


class ProfileConfig(BaseModel):
    """A profile (L3): default model/role, role overrides, and member registration."""

    model_config = ConfigDict(extra="forbid")

    default: str | None = None
    roles: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> "ProfileConfig":
        if self.default is None and not self.models:
            raise ValueError("a profile must declare 'default' or 'models'")
        if self.roles and self.default is None:
            raise ValueError("'roles' requires 'default'")
        for r in self.roles:
            if r not in NON_DEFAULT_ROLES:
                raise ValueError(
                    f"unknown profile role {r!r} (valid: {', '.join(NON_DEFAULT_ROLES)})"
                )
        return self


class CoreConfig(BaseModel):
    """The whole ``config.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: int
    providers: dict[str, ProviderConfig]
    profiles: dict[str, ProfileConfig]

    @field_validator("version")
    @classmethod
    def _version(cls, v: int) -> int:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported config version {v}; ACM 0.4 reads only version {SCHEMA_VERSION} "
                "(regenerate with `acm init --force`)"
            )
        return v

    @model_validator(mode="after")
    def _cross_refs(self) -> "CoreConfig":
        if not self.providers:
            raise ValueError("at least one provider is required")
        if not self.profiles:
            raise ValueError("at least one profile is required")
        for name in self.providers:
            if not PROVIDER_NAME.match(name):
                raise ValueError(f"invalid provider name {name!r}: use letters, digits, '_', '-'")
        for pname, prof in self.profiles.items():
            seen: dict[tuple[str, str], str] = {}
            refs: list[tuple[str, str]] = []
            if prof.default is not None:
                refs.append(("default", prof.default))
            refs.extend((f"roles.{k}", v) for k, v in prof.roles.items())
            refs.extend((f"models.{k}", v) for k, v in prof.models.items())
            for where, text in refs:
                try:
                    ref = self.check_ref(text)
                except ConfigError as e:
                    raise ValueError(f"profile {pname!r} {where}: {e.message}") from e
                if where.startswith("models.") and isinstance(ref, ModelRef) and ref.provider:
                    key = (ref.provider, ref.id)
                    if key in seen:
                        raise ValueError(
                            f"profile {pname!r}: {where} and {seen[key]} resolve to the same model"
                        )
                    seen[key] = where
        return self

    def check_ref(self, text: str) -> ModelRef | RoleRef:
        """Validate a reference against this config; returns the qualified reference."""
        ref = parse_ref(text, self.providers)
        if isinstance(ref, RoleRef):
            prov = self.providers[ref.provider]
            if not prov.is_manifest and not any(ref.role in m.roles for m in prov.models.values()):
                raise ConfigError(
                    f"provider {ref.provider!r} declares no model with role {ref.role!r}"
                )
            return ref
        if ref.provider is not None:
            prov = self.providers[ref.provider]
            if not prov.is_manifest and ref.id not in prov.models:
                raise ConfigError(f"provider {ref.provider!r} has no model {ref.id!r}")
            return ref
        hits = [n for n, p in self.providers.items() if not p.is_manifest and ref.id in p.models]
        if not hits:
            raise ConfigError(
                f"unknown model {ref.id!r} "
                "(manifest providers need 'provider.id' or 'provider@role')"
            )
        if len(hits) > 1:
            raise ConfigError(
                f"ambiguous model {ref.id!r} (declared by {', '.join(hits)}); "
                f"qualify it as 'provider.{ref.id}'"
            )
        return ModelRef(provider=hits[0], id=ref.id)
