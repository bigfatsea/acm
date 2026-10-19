"""TOML documents via tomlkit (lossless round-trip)."""

from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.toml_document import TOMLDocument

from acm.core.errors import FormatError
from acm.formats.base import MISSING, KeyPath, fmt_path, strict_equal


def _plain(x: Any) -> Any:
    return x.unwrap() if hasattr(x, "unwrap") else x


class TomlDocument:
    format = "toml"

    def __init__(self, doc: TOMLDocument) -> None:
        self._doc = doc

    @classmethod
    def parse(cls, data: bytes) -> "TomlDocument":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise FormatError(f"not valid UTF-8: {e}") from e
        try:
            return cls(tomlkit.parse(text))
        except TOMLKitError as e:
            raise FormatError(f"invalid TOML: {e}") from e

    def render(self) -> bytes:
        return tomlkit.dumps(self._doc).encode("utf-8")

    def tree(self) -> Any:
        return self._doc.unwrap()

    def get(self, path: KeyPath) -> Any:
        node: Any = self._doc
        for seg in path:
            try:
                node = node[seg]
            except (KeyError, IndexError, TypeError):
                return MISSING
        return _plain(node)

    def set(self, path: KeyPath, value: Any) -> None:
        if not path:
            raise FormatError("cannot replace the document root")
        if value is None:
            raise FormatError("TOML has no null; use delete()")
        node: Any = self._doc
        for depth, seg in enumerate(path[:-1]):
            try:
                node = node[seg]
            except (KeyError, IndexError):
                self._create_chain(node, path[depth:], value)
                return
            except TypeError as e:
                raise FormatError(
                    f"cannot set {fmt_path(path)}: {fmt_path(path[:depth])} is not a table"
                ) from e
            if not hasattr(node, "keys") and not isinstance(node, list):
                raise FormatError(
                    f"cannot set {fmt_path(path)}: {fmt_path(path[: depth + 1])} is not a table"
                )
        leaf = path[-1]
        try:
            existing = node[leaf]
        except (KeyError, IndexError):
            pass
        except TypeError as e:
            raise FormatError(f"cannot set {fmt_path(path)}") from e
        else:
            if strict_equal(_plain(existing), value):
                return
        try:
            node[leaf] = value
        except (TypeError, ValueError, TOMLKitError) as e:
            raise FormatError(f"cannot set {fmt_path(path)}: {e}") from e

    @staticmethod
    def _create_chain(container: Any, rest: KeyPath, value: Any) -> None:
        """Create the tables for ``rest``; its first segment is absent from ``container``."""
        if not all(isinstance(s, str) for s in rest):
            raise FormatError("cannot create array elements implicitly")
        names = [str(s) for s in rest]
        if len(names) == 1:
            container[names[0]] = value
            return
        inner = tomlkit.table()
        inner[names[-1]] = value
        cur: Any = inner
        for name in reversed(names[1:-1]):
            parent = tomlkit.table(is_super_table=True)
            parent[name] = cur
            cur = parent
        container[names[0]] = cur

    def delete(self, path: KeyPath) -> None:
        if not path:
            raise FormatError("cannot delete the document root")
        node: Any = self._doc
        for seg in path[:-1]:
            try:
                node = node[seg]
            except (KeyError, IndexError, TypeError):
                return
        try:
            del node[path[-1]]
        except (KeyError, IndexError, TypeError):
            return
