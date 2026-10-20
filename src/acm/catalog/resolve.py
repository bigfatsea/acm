"""Build the catalog from config and resolve a profile for one agent (role x protocol)."""

from dataclasses import dataclass, field

from acm.catalog.manifest import load_manifest_provider
from acm.catalog.model import ModelCard, Provider, ResolvedModel, ResolvedTarget
from acm.catalog.static import static_provider
from acm.config.refs import ModelRef, RoleRef, parse_credential
from acm.config.schema import CoreConfig
from acm.core.context import Ctx
from acm.core.errors import ACMError, ConfigError
from acm.engine.model import ProjectionWarning


class TargetError(Exception):
    """The profile cannot be projected onto *this* agent (other agents are unaffected)."""


@dataclass
class Catalog:
    providers: dict[str, Provider] = field(default_factory=dict)
    errors: dict[str, ACMError] = field(default_factory=dict)

    def notes(self) -> list[str]:
        return [n for p in self.providers.values() for n in (p.note, *p.warnings) if n]


def build_catalog(ctx: Ctx, config: CoreConfig, needed: set[str] | None = None) -> Catalog:
    """Load the providers in ``needed`` (default: all). A provider that fails to load is recorded
    in ``errors``; the caller decides whether that is fatal."""
    cat = Catalog()
    for name, pcfg in config.providers.items():
        if needed is not None and name not in needed:
            continue
        if not pcfg.is_manifest:
            cat.providers[name] = static_provider(name, pcfg)
            continue
        assert pcfg.manifest is not None
        try:
            cat.providers[name] = load_manifest_provider(
                ctx, name, pcfg.manifest, parse_credential(pcfg.api_key), pcfg.headers
            )
        except ACMError as e:
            cat.errors[name] = e
    return cat


def profile_providers(config: CoreConfig, profile: str) -> set[str]:
    """The providers a profile refers to."""
    prof = config.profiles[profile]
    texts = [t for t in [prof.default, *prof.roles.values(), *prof.models.values()] if t]
    out: set[str] = set()
    for t in texts:
        ref = config.check_ref(t)
        assert ref.provider is not None
        out.add(ref.provider)
    return out


def _select_protocol(card: ModelCard, protocols: tuple[str, ...]) -> str | None:
    return next((p for p in protocols if p in card.protocols), None)


def _resolve_model(
    config: CoreConfig, catalog: Catalog, text: str, protocols: tuple[str, ...]
) -> ResolvedModel:
    ref = config.check_ref(text)
    assert ref.provider is not None
    if ref.provider in catalog.errors:
        raise catalog.errors[ref.provider]
    provider = catalog.providers[ref.provider]
    if isinstance(ref, RoleRef):
        found: tuple[ModelCard, str] | None = None
        for p in protocols:
            cands = [c for c in provider.cards if ref.role in c.roles and p in c.protocols]
            if len(cands) > 1:
                raise ConfigError(
                    f"'{text}' is ambiguous on {p}: {', '.join(c.id for c in cands)} all claim "
                    f"role '{ref.role}'"
                )
            if cands:
                found = (cands[0], p)
                break
        if found is None:
            raise TargetError(
                f"'{text}': provider '{provider.name}' has no model with role '{ref.role}' on "
                f"{' / '.join(protocols)}"
            )
        return ResolvedModel(provider, found[0], found[1])
    assert isinstance(ref, ModelRef)
    card = provider.card(ref.id)
    if card is None:
        known = ", ".join(c.id for c in provider.cards[:12])
        raise ConfigError(
            f"model '{ref.id}' is not offered by provider '{provider.name}' (offered: {known})"
        )
    proto = _select_protocol(card, protocols)
    if proto is None:
        raise TargetError(
            f"'{text}' speaks {' / '.join(card.protocols)}, which this agent cannot use "
            f"(it needs {' / '.join(protocols)})"
        )
    return ResolvedModel(provider, card, proto)


def resolve_target(
    config: CoreConfig,
    catalog: Catalog,
    profile_name: str,
    protocols: tuple[str, ...],
    agent: str,
) -> ResolvedTarget:
    """Resolve ``profile_name`` for an agent that can speak ``protocols`` (preference order).

    Raises ConfigError for problems that affect every agent (unknown model, unusable gateway)
    and TargetError when only this agent cannot be served.
    """
    prof = config.profiles[profile_name]
    warnings: list[ProjectionWarning] = []
    if prof.default is None:
        raise TargetError(
            f"profile '{profile_name}' declares no default model, so there is nothing to project"
        )
    default = _resolve_model(config, catalog, prof.default, protocols)
    roles: dict[str, ResolvedModel | None] = {}
    for role, text in prof.roles.items():
        try:
            roles[role] = _resolve_model(config, catalog, text, protocols)
        except TargetError as e:
            roles[role] = None
            warnings.append(ProjectionWarning(f"roles.{role}", str(e), agent))
    members: dict[str, ResolvedModel] = {}
    for label, text in prof.models.items():
        try:
            members[label] = _resolve_model(config, catalog, text, protocols)
        except TargetError as e:
            warnings.append(ProjectionWarning(f"models.{label}", str(e), agent))
    for field_name, m in [
        ("default", default),
        *((f"roles.{r}", rm) for r, rm in roles.items()),
        *((f"models.{k}", mm) for k, mm in members.items()),
    ]:
        if m is not None and m.card.tool_call is False:
            warnings.append(
                ProjectionWarning(
                    field_name,
                    f"'{m.id}' has no tool-capable model behind it; coding agents send tools on "
                    "every turn, so those requests will fail (a gateway refuses them)",
                    agent,
                )
            )
    return ResolvedTarget(profile_name, default, roles, members, warnings)
