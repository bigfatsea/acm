"""Format layer interface: parse/edit agent config files while preserving what we don't touch."""

from collections.abc import Iterator
from typing import Any, Protocol

from acm.core.errors import FormatError

KeyPath = tuple[str | int, ...]

FORMATS = ("json", "jsonc", "json5", "toml", "yaml")


class _Missing:
    """Sentinel for "no value at this path" (distinct from an explicit null)."""

    _instance: "_Missing | None" = None

    def __new__(cls) -> "_Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Any = _Missing()


class Document(Protocol):
    """An editable view of one config file."""

    format: str

    def get(self, path: KeyPath) -> Any:
        """Value at ``path`` as plain Python data, or ``MISSING``."""
        ...

    def set(self, path: KeyPath, value: Any) -> None:
        """Set ``path``; missing intermediate objects are created."""
        ...

    def delete(self, path: KeyPath) -> None:
        """Remove ``path``; a no-op when absent."""
        ...

    def render(self) -> bytes:
        """The file content; unmodified regions are kept byte-for-byte where possible."""
        ...

    def tree(self) -> Any:
        """The whole document as plain Python data (for semantic comparison)."""
        ...


def parse(fmt: str, data: bytes) -> Document:
    """Parse ``data`` as ``fmt``; raises FormatError when it is not valid."""
    if fmt in ("json", "jsonc", "json5"):
        from acm.formats.jsonc import JsoncDocument

        return JsoncDocument.parse(fmt, data)
    if fmt == "toml":
        from acm.formats.toml import TomlDocument

        return TomlDocument.parse(data)
    if fmt == "yaml":
        from acm.formats.yaml import YamlDocument

        return YamlDocument.parse(data)
    raise FormatError(f"unsupported format {fmt!r}")


def empty(fmt: str) -> Document:
    """A document for a file that does not exist yet."""
    if fmt in ("json", "jsonc", "json5"):
        from acm.formats.jsonc import JsoncDocument

        return JsoncDocument.parse(fmt, b"{}\n")
    return parse(fmt, b"")


def strict_equal(a: Any, b: Any) -> bool:
    """Equality that does not conflate ``True``/``1`` or ``1``/``1.0``."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def changed_paths(a: Any, b: Any, prefix: KeyPath = ()) -> Iterator[KeyPath]:
    """Yield the shallowest paths at which trees ``a`` and ``b`` differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() | b.keys():
            if k not in a or k not in b:
                yield (*prefix, k)
            else:
                yield from changed_paths(a[k], b[k], (*prefix, k))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield prefix
        else:
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                yield from changed_paths(x, y, (*prefix, i))
    elif not strict_equal(a, b):
        yield prefix


def leaf_changes(path: KeyPath, a: Any, b: Any) -> Iterator[tuple[KeyPath, Any, Any]]:
    """Narrow a change of ``path`` from ``a`` to ``b`` down to the leaves that differ (for
    display: a changed provider entry reads as its one changed field)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in [*a, *(k for k in b if k not in a)]:
            av, bv = a.get(k, MISSING), b.get(k, MISSING)
            if not strict_equal(av, bv):
                yield from leaf_changes((*path, k), av, bv)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            if not strict_equal(x, y):
                yield from leaf_changes((*path, i), x, y)
    else:
        yield path, a, b


def path_covers(op_path: KeyPath, changed: KeyPath) -> bool:
    """True when an operation on ``op_path`` legitimately explains a change at ``changed``."""
    return changed[: len(op_path)] == op_path


def fmt_path(path: KeyPath) -> str:
    """Human-readable path, e.g. ``env.ANTHROPIC_BASE_URL`` or ``models[0].id``."""
    out = ""
    for seg in path:
        if isinstance(seg, int):
            out += f"[{seg}]"
        else:
            out += f".{seg}" if out else seg
    return out or "<root>"
