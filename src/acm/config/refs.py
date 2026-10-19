"""Reference syntaxes: credentials (``${VAR}``) and model / role references."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from acm.core.errors import ConfigError

Role = Literal["default", "reasoning", "fast", "subagent", "review"]
ROLES: tuple[str, ...] = get_args(Role)
NON_DEFAULT_ROLES: tuple[str, ...] = tuple(r for r in ROLES if r != "default")

_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}$")
PROVIDER_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class CredentialRef:
    """A credential as written in config: a whole-field ``${VAR}`` reference or a literal."""

    raw: str
    var: str | None
    default: str | None

    @property
    def is_reference(self) -> bool:
        return self.var is not None

    def resolve(self, env: Mapping[str, str]) -> str:
        """Return the live value; raise ConfigError when a referenced variable is unset."""
        if self.var is None:
            return self.raw
        value = env.get(self.var, "")
        if value != "":
            return value
        if self.default is not None:
            return self.default
        raise ConfigError(
            f"environment variable {self.var} is not set (referenced by '{self.raw}')"
        )

    def try_resolve(self, env: Mapping[str, str]) -> str | None:
        try:
            return self.resolve(env)
        except ConfigError:
            return None


def parse_credential(raw: str) -> CredentialRef:
    """Parse a credential field. Only strict whole-field references are supported."""
    m = _ENV_REF.match(raw)
    if m:
        return CredentialRef(raw=raw, var=m.group(1), default=m.group(2))
    if "${" in raw or "}" in raw:
        raise ConfigError(
            f"invalid credential reference {raw!r}: only whole-field '${{VAR}}' or "
            "'${VAR:-default}' is supported (no interpolation or nesting)"
        )
    return CredentialRef(raw=raw, var=None, default=None)


@dataclass(frozen=True)
class ModelRef:
    """A model reference; ``provider`` is None for a bare id."""

    provider: str | None
    id: str


@dataclass(frozen=True)
class RoleRef:
    provider: str
    role: str


Ref = ModelRef | RoleRef


def parse_ref(text: str, providers: Mapping[str, object]) -> Ref:
    """Parse ``provider@role``, ``provider.id`` or a bare ``id``.

    A reference is qualified when the text before the *first* dot names a declared
    provider, so model ids may themselves contain dots.
    """
    text = text.strip()
    if not text:
        raise ConfigError("empty model reference")
    if "@" in text:
        prov, _, role = text.partition("@")
        if prov not in providers:
            raise ConfigError(f"role reference {text!r}: unknown provider {prov!r}")
        if role not in ROLES:
            raise ConfigError(
                f"role reference {text!r}: unknown role {role!r} (valid: {', '.join(ROLES)})"
            )
        return RoleRef(provider=prov, role=role)
    left, dot, right = text.partition(".")
    if dot and left in providers and right:
        return ModelRef(provider=left, id=right)
    return ModelRef(provider=None, id=text)
