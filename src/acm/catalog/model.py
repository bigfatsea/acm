"""Runtime catalog types: model cards, providers, and the per-agent resolved target."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from acm.config.refs import CredentialRef
from acm.engine.model import ProjectionWarning

PROTOCOL_ORDER = ("openai-completions", "anthropic-messages", "openai-responses")


@dataclass(frozen=True)
class ModelCard:
    """What is known about one model. ``None`` means unknown, never "no"."""

    provider: str
    id: str
    protocols: tuple[str, ...]
    roles: tuple[str, ...] = ()
    display_name: str | None = None
    description: str | None = None
    context: int | None = None
    context_floor: int | None = None
    output: int | None = None
    input: tuple[str, ...] = ("text",)
    tool_call: bool | None = None
    reasoning: bool | None = None
    effort: str | None = None

    @property
    def effective_context(self) -> int | None:
        """The window agents should assume: the conservative floor when the gateway has one."""
        return self.context_floor or self.context


@dataclass(frozen=True)
class Provider:
    name: str
    endpoints: Mapping[str, str]
    credential: CredentialRef
    cards: tuple[ModelCard, ...]
    headers: Mapping[str, str] = field(default_factory=dict)
    origin: Literal["static", "manifest"] = "static"
    source: str | None = None
    note: str | None = None  # e.g. "manifest served from cache (fetched 2h ago)"
    warnings: tuple[str, ...] = ()  # e.g. endpoints on another origin than the manifest

    def card(self, model_id: str) -> ModelCard | None:
        for c in self.cards:
            if c.id == model_id:
                return c
        return None

    @property
    def protocols(self) -> tuple[str, ...]:
        return tuple(p for p in PROTOCOL_ORDER if p in self.endpoints)

    @property
    def primary_protocol(self) -> str:
        return self.protocols[0]


@dataclass(frozen=True)
class ResolvedModel:
    provider: Provider
    card: ModelCard
    protocol: str

    @property
    def base_url(self) -> str:
        return self.provider.endpoints[self.protocol]

    @property
    def id(self) -> str:
        return self.card.id


@dataclass
class ResolvedTarget:
    """Everything an adapter needs, already resolved for that adapter's protocols."""

    profile: str
    default: ResolvedModel
    roles: dict[str, ResolvedModel | None] = field(default_factory=dict)
    members: dict[str, ResolvedModel] = field(default_factory=dict)
    warnings: list[ProjectionWarning] = field(default_factory=list)

    @property
    def provider(self) -> Provider:
        return self.default.provider

    def role(self, name: str) -> ResolvedModel | None:
        return self.default if name == "default" else self.roles.get(name)

    def all_models(self) -> list[ResolvedModel]:
        """Default, then roles, then members, de-duplicated by (provider, id, protocol)."""
        seen: dict[tuple[str, str, str], ResolvedModel] = {}
        for m in [self.default, *self.roles.values(), *self.members.values()]:
            if m is not None:
                seen.setdefault((m.provider.name, m.id, m.protocol), m)
        return list(seen.values())
