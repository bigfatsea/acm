"""YAML documents via ruamel.yaml round-trip (comments and key order preserved)."""

import re
from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from acm.core.errors import FormatError
from acm.formats.base import MISSING, KeyPath, fmt_path, strict_equal


def _plain(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    if isinstance(x, bool):
        return bool(x)
    if isinstance(x, int):
        return int(x)
    if isinstance(x, float):
        return float(x)
    if isinstance(x, str):
        return str(x)
    return x


def _detect_indent(text: str) -> tuple[int, int, int]:
    """Best-effort (mapping, sequence, offset) so re-emission matches the file's style."""
    mapping = 2
    seq, off = 4, 2
    lines = text.splitlines()
    leads = [
        len(ln) - len(ln.lstrip(" "))
        for ln in lines
        if ln.strip() and not ln.lstrip().startswith(("#", "-"))
    ]
    positives = [x for x in leads if x > 0]
    if positives:
        mapping = min(positives)
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)- ", ln)
        if not m:
            continue
        for j in range(i - 1, -1, -1):
            prev = lines[j]
            if prev.strip() and not prev.lstrip().startswith("#"):
                if prev.rstrip().endswith(":"):
                    parent = len(prev) - len(prev.lstrip(" "))
                    off = len(m.group(1)) - parent
                    seq = off + 2
                break
        break
    return mapping, seq, off


class YamlDocument:
    format = "yaml"

    def __init__(self, text: str) -> None:
        self._original = text
        self._dirty = False
        self._yaml = YAML(typ="rt")
        self._yaml.preserve_quotes = True
        self._yaml.width = 4096
        m, s, o = _detect_indent(text)
        self._yaml.indent(mapping=m, sequence=s, offset=o)
        try:
            data = self._yaml.load(text) if text.strip() else None
        except YAMLError as e:
            raise FormatError(f"invalid YAML: {e}") from e
        if data is None:
            data = CommentedMap()
        if not isinstance(data, CommentedMap):
            raise FormatError("the top-level YAML value must be a mapping")
        self._root: CommentedMap = data

    @classmethod
    def parse(cls, data: bytes) -> "YamlDocument":
        try:
            return cls(data.decode("utf-8"))
        except UnicodeDecodeError as e:
            raise FormatError(f"not valid UTF-8: {e}") from e

    def render(self) -> bytes:
        if not self._dirty:
            return self._original.encode("utf-8")
        buf = StringIO()
        self._yaml.dump(self._root, buf)
        return buf.getvalue().encode("utf-8")

    def tree(self) -> Any:
        return _plain(self._root)

    def get(self, path: KeyPath) -> Any:
        node: Any = self._root
        for seg in path:
            try:
                node = node[seg]
            except (KeyError, IndexError, TypeError):
                return MISSING
        return _plain(node)

    def set(self, path: KeyPath, value: Any) -> None:
        if not path:
            raise FormatError("cannot replace the document root")
        node: Any = self._root
        for depth, seg in enumerate(path[:-1]):
            try:
                nxt = node[seg]
            except (KeyError, IndexError):
                nxt = None
                if not isinstance(seg, str):
                    raise FormatError("cannot create array elements implicitly") from None
            except TypeError as e:
                raise FormatError(f"cannot set {fmt_path(path)}") from e
            if nxt is None:
                nxt = CommentedMap()
                self._assign(node, seg, nxt)
            elif not isinstance(nxt, (dict, list)):
                raise FormatError(
                    f"cannot set {fmt_path(path)}: {fmt_path(path[: depth + 1])} is not a container"
                )
            node = nxt
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
        self._assign(node, leaf, value)

    def _assign(self, node: Any, key: str | int, value: Any) -> None:
        try:
            if isinstance(node, CommentedSeq) and isinstance(key, int) and key == len(node):
                node.append(value)
            else:
                node[key] = value
        except (TypeError, IndexError) as e:
            raise FormatError(f"cannot assign {key!r}: {e}") from e
        self._dirty = True

    def delete(self, path: KeyPath) -> None:
        if not path:
            raise FormatError("cannot delete the document root")
        node: Any = self._root
        for seg in path[:-1]:
            try:
                node = node[seg]
            except (KeyError, IndexError, TypeError):
                return
        try:
            del node[path[-1]]
        except (KeyError, IndexError, TypeError):
            return
        self._dirty = True
