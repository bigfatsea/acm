"""JSON / JSONC / JSON5 editor that replaces only the bytes it must change.

One tolerant parser accepts the JSON5 superset (comments, trailing commas, unquoted keys,
single-quoted strings, hex numbers, ``+``/``-`` signs, ``Infinity``/``NaN``) and builds a
concrete syntax tree with source offsets. Edits are computed as ``(start, end, text)``
splices on the original text and the tree is re-parsed afterwards, so everything outside a
splice — comments, indentation, quote style, key order, trailing commas — is untouched.
"""

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from acm.core.errors import FormatError
from acm.formats.base import MISSING, KeyPath, fmt_path, strict_equal

_NUMBER = re.compile(
    r"[+-]?(?:Infinity|NaN|0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)
_LITERALS = {"true": True, "false": False, "null": None}
_ESCAPES = {
    "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "0": "\0",
    "'": "'", '"': '"', "\\": "\\", "/": "/",
}  # fmt: skip
_MAX_DEPTH = 200


# ---------------------------------------------------------------- syntax tree


@dataclass
class Node:
    start: int
    end: int


@dataclass
class Scalar(Node):
    kind: str  # "string" | "number" | "literal"
    value: Any


@dataclass
class Member:
    key: str
    key_start: int
    value: "Node"
    comma: int | None = None  # offset of the "," that follows this member

    @property
    def end(self) -> int:
        return self.value.end


@dataclass
class Item:
    value: "Node"
    comma: int | None = None

    @property
    def start(self) -> int:
        return self.value.start

    @property
    def end(self) -> int:
        return self.value.end


@dataclass
class Obj(Node):
    members: list[Member] = field(default_factory=list)


@dataclass
class Arr(Node):
    items: list[Item] = field(default_factory=list)


def to_py(node: Node) -> Any:
    if isinstance(node, Scalar):
        return node.value
    if isinstance(node, Obj):
        return {m.key: to_py(m.value) for m in node.members}
    assert isinstance(node, Arr)
    return [to_py(i.value) for i in node.items]


# --------------------------------------------------------------------- parser


class _Parser:
    def __init__(self, text: str) -> None:
        self.t = text
        self.i = 0
        self.n = len(text)

    def error(self, msg: str, at: int | None = None) -> FormatError:
        pos = self.i if at is None else at
        line = self.t.count("\n", 0, pos) + 1
        col = pos - (self.t.rfind("\n", 0, pos) + 1) + 1
        return FormatError(f"{msg} at line {line}, column {col}")

    def ws(self) -> None:
        t, n = self.t, self.n
        while self.i < n:
            c = t[self.i]
            if c.isspace() or c == "﻿":
                self.i += 1
            elif t.startswith("//", self.i):
                j = t.find("\n", self.i)
                self.i = n if j < 0 else j
            elif t.startswith("/*", self.i):
                j = t.find("*/", self.i + 2)
                if j < 0:
                    raise self.error("unterminated comment")
                self.i = j + 2
            else:
                break

    def parse_root(self) -> Node:
        self.ws()
        if self.i >= self.n:
            raise self.error("empty document")
        node = self.value(0)
        self.ws()
        if self.i != self.n:
            raise self.error("unexpected content after the top-level value")
        return node

    def value(self, depth: int) -> Node:
        if depth > _MAX_DEPTH:
            raise self.error("nesting too deep")
        if self.i >= self.n:
            raise self.error("unexpected end of input")
        c = self.t[self.i]
        if c == "{":
            return self.obj(depth)
        if c == "[":
            return self.arr(depth)
        if c in "\"'":
            start = self.i
            s = self.string()
            return Scalar(start, self.i, "string", s)
        for lit, val in _LITERALS.items():
            if self.t.startswith(lit, self.i) and not self._ident_char(self.i + len(lit)):
                start = self.i
                self.i += len(lit)
                return Scalar(start, self.i, "literal", val)
        m = _NUMBER.match(self.t, self.i)
        if m:
            start = self.i
            self.i = m.end()
            return Scalar(start, self.i, "number", _number(m.group()))
        raise self.error(f"unexpected character {c!r}")

    def _ident_char(self, pos: int) -> bool:
        if pos >= self.n:
            return False
        c = self.t[pos]
        return c.isalnum() or c in "_$"

    def key(self) -> tuple[str, int]:
        start = self.i
        c = self.t[self.i]
        if c in "\"'":
            return self.string(), start
        if c.isalpha() or c in "_$":
            j = self.i + 1
            while j < self.n and (self.t[j].isalnum() or self.t[j] in "_$"):
                j += 1
            self.i = j
            return self.t[start:j], start
        raise self.error("expected an object key")

    def obj(self, depth: int) -> Obj:
        node = Obj(self.i, self.i)
        self.i += 1
        while True:
            self.ws()
            if self.i >= self.n:
                raise self.error("unterminated object", node.start)
            if self.t[self.i] == "}":
                self.i += 1
                node.end = self.i
                return node
            key, kstart = self.key()
            self.ws()
            if self.i >= self.n or self.t[self.i] != ":":
                raise self.error("expected ':' after object key")
            self.i += 1
            self.ws()
            member = Member(key, kstart, self.value(depth + 1))
            node.members.append(member)
            self.ws()
            if self.i < self.n and self.t[self.i] == ",":
                member.comma = self.i
                self.i += 1
            elif self.i < self.n and self.t[self.i] == "}":
                pass
            else:
                raise self.error("expected ',' or '}' in object")

    def arr(self, depth: int) -> Arr:
        node = Arr(self.i, self.i)
        self.i += 1
        while True:
            self.ws()
            if self.i >= self.n:
                raise self.error("unterminated array", node.start)
            if self.t[self.i] == "]":
                self.i += 1
                node.end = self.i
                return node
            item = Item(self.value(depth + 1))
            node.items.append(item)
            self.ws()
            if self.i < self.n and self.t[self.i] == ",":
                item.comma = self.i
                self.i += 1
            elif self.i < self.n and self.t[self.i] == "]":
                pass
            else:
                raise self.error("expected ',' or ']' in array")

    def string(self) -> str:
        quote = self.t[self.i]
        start = self.i
        self.i += 1
        out: list[str] = []
        t, n = self.t, self.n
        while True:
            if self.i >= n:
                raise self.error("unterminated string", start)
            c = t[self.i]
            if c == quote:
                self.i += 1
                return "".join(out)
            if c == "\n":
                raise self.error("newline in string", start)
            if c != "\\":
                out.append(c)
                self.i += 1
                continue
            self.i += 1
            if self.i >= n:
                raise self.error("unterminated string", start)
            e = t[self.i]
            if e in _ESCAPES:
                out.append(_ESCAPES[e])
                self.i += 1
            elif e == "\n":
                self.i += 1
            elif e == "\r":
                self.i += 2 if t.startswith("\r\n", self.i) else 1
            elif e == "x":
                out.append(self._hex(2))
            elif e == "u":
                cp = self._hex_code(4)
                if 0xD800 <= cp < 0xDC00 and t.startswith("\\u", self.i):
                    self.i += 1  # now at the "u"; _hex_code skips it
                    low = self._hex_code(4)
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00)
                out.append(chr(cp))
            else:
                out.append(e)
                self.i += 1

    def _hex_code(self, digits: int) -> int:
        self.i += 1  # skip the x / u already consumed by the caller's escape letter
        chunk = self.t[self.i : self.i + digits]
        if len(chunk) != digits or not re.fullmatch(r"[0-9a-fA-F]+", chunk):
            raise self.error("invalid unicode escape")
        self.i += digits
        return int(chunk, 16)

    def _hex(self, digits: int) -> str:
        return chr(self._hex_code(digits))


def _number(text: str) -> int | float:
    sign = -1 if text.startswith("-") else 1
    body = text.lstrip("+-")
    if body == "Infinity":
        return sign * math.inf
    if body == "NaN":
        return math.nan
    if body[:2] in ("0x", "0X"):
        return sign * int(body, 16)
    if re.fullmatch(r"\d+", body):
        return sign * int(body)
    return sign * float(body)


# ------------------------------------------------------------------ serialize


def _is_scalar(v: Any) -> bool:
    return not isinstance(v, (dict, list))


def _scalar_json(v: Any) -> str:
    if isinstance(v, float) and not math.isfinite(v):
        raise FormatError("cannot write a non-finite number")
    if isinstance(v, (str, int, float, bool)) or v is None:
        return json.dumps(v, ensure_ascii=False)
    raise FormatError(f"cannot serialise {type(v).__name__} to JSON")


# ------------------------------------------------------------------- document


class JsoncDocument:
    """A JSON/JSONC/JSON5 document edited by splicing the original text."""

    def __init__(self, fmt: str, text: str, bom: bool) -> None:
        self.format = fmt
        self._text = text
        self._bom = bom
        self._root = self._parse_text(text)

    # ---- construction / output

    @classmethod
    def parse(cls, fmt: str, data: bytes) -> "JsoncDocument":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise FormatError(f"not valid UTF-8: {e}") from e
        bom = text.startswith("﻿")
        if bom:
            text = text[1:]
        if not text.strip():
            text = "{}\n"
        return cls(fmt, text, bom)

    @staticmethod
    def _parse_text(text: str) -> Obj:
        root = _Parser(text).parse_root()
        if not isinstance(root, Obj):
            raise FormatError("the top-level value must be an object")
        return root

    def render(self) -> bytes:
        return (("﻿" if self._bom else "") + self._text).encode("utf-8")

    def tree(self) -> Any:
        return to_py(self._root)

    # ---- reading

    def get(self, path: KeyPath) -> Any:
        node = self._descend(path)
        return MISSING if node is None else to_py(node)

    def _descend(self, path: KeyPath) -> Node | None:
        node: Node = self._root
        for seg in path:
            if isinstance(seg, str) and isinstance(node, Obj):
                m = _last_member(node, seg)
                if m is None:
                    return None
                node = m.value
            elif isinstance(seg, int) and isinstance(node, Arr):
                if not 0 <= seg < len(node.items):
                    return None
                node = node.items[seg].value
            else:
                return None
        return node

    # ---- editing

    def set(self, path: KeyPath, value: Any) -> None:
        if not path:
            raise FormatError("cannot replace the document root")
        node: Node = self._root
        for depth, seg in enumerate(path):
            rest = path[depth + 1 :]
            if isinstance(seg, str) and isinstance(node, Obj):
                m = _last_member(node, seg)
                if m is None:
                    self._insert_member(node, seg, _nest(rest, value))
                    return
                if depth == len(path) - 1:
                    self._replace(m.value, value)
                    return
                if isinstance(m.value, Scalar) and m.value.value is None:
                    self._replace(m.value, _nest(rest, value))
                    return
                node = m.value
            elif isinstance(seg, int) and isinstance(node, Arr):
                if 0 <= seg < len(node.items):
                    if depth == len(path) - 1:
                        self._replace(node.items[seg].value, value)
                        return
                    node = node.items[seg].value
                elif seg == len(node.items) and depth == len(path) - 1:
                    self._insert_item(node, value)
                    return
                else:
                    raise FormatError(f"array index {seg} out of range at {fmt_path(path[:depth])}")
            else:
                raise FormatError(
                    f"cannot set {fmt_path(path)}: {fmt_path(path[:depth]) or '<root>'} "
                    f"is not a container for {seg!r}"
                )

    def delete(self, path: KeyPath) -> None:
        if not path:
            raise FormatError("cannot delete the document root")
        parent = self._descend(path[:-1])
        seg = path[-1]
        if isinstance(parent, Obj) and isinstance(seg, str):
            members = [m for m in parent.members if m.key == seg]
            # remove from the back so earlier offsets stay valid while re-parsing each time
            for _ in members:
                current = self._descend(path[:-1])
                assert isinstance(current, Obj)
                m = _last_member(current, seg)
                if m is None:
                    return
                self._remove(current, current.members.index(m))
        elif isinstance(parent, Arr) and isinstance(seg, int) and 0 <= seg < len(parent.items):
            self._remove(parent, seg)

    # ---- splice helpers

    def _apply(self, start: int, end: int, replacement: str) -> None:
        text = self._text[:start] + replacement + self._text[end:]
        self._root = self._parse_text(text)
        self._text = text

    @property
    def _nl(self) -> str:
        return "\r\n" if "\r\n" in self._text else "\n"

    def _unit(self) -> str:
        best: int | None = None
        for line in self._text.splitlines():
            stripped = line.lstrip(" \t")
            if not stripped or stripped[0] in "/*":
                continue
            lead = line[: len(line) - len(stripped)]
            if "\t" in lead:
                return "\t"
            if lead and (best is None or len(lead) < best):
                best = len(lead)
        return " " * (best or 2)

    def _line_start(self, pos: int) -> int:
        return self._text.rfind("\n", 0, pos) + 1

    def _line_indent(self, pos: int) -> str:
        ls = self._line_start(pos)
        j = ls
        while j < len(self._text) and self._text[j] in " \t":
            j += 1
        return self._text[ls:j]

    def _dump(self, value: Any, indent: str, inline: bool = False) -> str:
        """Serialise ``value``; nested lines are indented relative to ``indent``."""
        if _is_scalar(value):
            return _scalar_json(value)
        unit = self._unit()
        nl = self._nl
        if isinstance(value, list):
            if not value:
                return "[]"
            if inline or all(_is_scalar(v) for v in value):
                return "[" + ", ".join(self._dump(v, indent, True) for v in value) + "]"
            inner = indent + unit
            body = f",{nl}".join(inner + self._dump(v, inner) for v in value)
            return f"[{nl}{body}{nl}{indent}]"
        if not value:
            return "{}"
        if inline:
            pairs = (f"{json.dumps(k, ensure_ascii=False)}: {self._dump(v, indent, True)}"
                     for k, v in value.items())  # fmt: skip
            return "{" + ", ".join(pairs) + "}"
        inner = indent + unit
        body = f",{nl}".join(
            f"{inner}{json.dumps(k, ensure_ascii=False)}: {self._dump(v, inner)}"
            for k, v in value.items()
        )
        return f"{{{nl}{body}{nl}{indent}}}"

    def _replace(self, node: Node, value: Any) -> None:
        if strict_equal(to_py(node), value):
            return
        compact = not isinstance(node, Scalar) and "\n" not in self._text[node.start : node.end]
        indent = self._line_indent(node.start)
        text = self._dump(value, indent, inline=compact)
        self._apply(node.start, node.end, text)

    def _line_tail_end(self, pos: int) -> int | None:
        """If only whitespace/comments remain on the line after ``pos``, return the offset of
        its end (the newline or end of text); otherwise None."""
        t, n = self._text, len(self._text)
        i = pos
        while i < n:
            c = t[i]
            if c in " \t\r":
                i += 1
            elif c == "\n":
                return i
            elif t.startswith("//", i):
                j = t.find("\n", i)
                return n if j < 0 else j
            elif t.startswith("/*", i):
                j = t.find("*/", i + 2)
                if j < 0 or "\n" in t[i:j]:
                    return None
                i = j + 2
            else:
                return None
        return n

    def _insert_member(self, obj: Obj, key: str, value: Any) -> None:
        t, nl, unit = self._text, self._nl, self._unit()
        qkey = json.dumps(key, ensure_ascii=False)
        if not obj.members:
            inner = t[obj.start + 1 : obj.end - 1]
            base = self._line_indent(obj.start)
            multi = obj is self._root or "\n" in t.strip() or "\n" in inner
            if inner.strip() == "":
                if multi:
                    ind = base + unit
                    member = f"{qkey}: {self._dump(value, ind)}"
                    self._apply(obj.start, obj.end, f"{{{nl}{ind}{member}{nl}{base}}}")
                else:
                    self._apply(obj.start, obj.end, f"{{{qkey}: {self._dump(value, base, True)}}}")
            else:
                ind = base + unit
                member = f"{qkey}: {self._dump(value, ind)}"
                self._apply(obj.end - 1, obj.end - 1, f"{ind}{member}{nl}{base}")
            return
        last = obj.members[-1]
        trailing = last.comma is not None
        p_end = last.comma + 1 if last.comma is not None else last.end
        tail = self._line_tail_end(p_end)
        if tail is None or "\n" not in t[obj.start : obj.end]:
            member = f"{qkey}: {self._dump(value, self._line_indent(last.key_start), True)}"
            if trailing:
                self._apply(p_end, p_end, f" {member},")
            else:
                self._apply(p_end, p_end, f", {member}")
            return
        key_line_start = self._line_start(last.key_start)
        lead = t[key_line_start : last.key_start]
        ind = lead if lead.strip() == "" else self._line_indent(obj.start) + unit
        member = f"{qkey}: {self._dump(value, ind)}"
        comma_fix = "" if trailing else ","
        between = t[p_end:tail]
        cr = "\r" if between.endswith("\r") else ""
        between = between.removesuffix("\r")
        self._apply(
            p_end, tail, f"{comma_fix}{between}{nl}{ind}{member}{',' if trailing else ''}{cr}"
        )

    def _insert_item(self, arr: Arr, value: Any) -> None:
        t, nl, unit = self._text, self._nl, self._unit()
        if not arr.items:
            inner = t[arr.start + 1 : arr.end - 1]
            if inner.strip() == "":
                base = self._line_indent(arr.start)
                if _is_scalar(value) or "\n" not in t.strip():
                    self._apply(arr.start, arr.end, f"[{self._dump(value, base, True)}]")
                else:
                    ind = base + unit
                    self._apply(
                        arr.start, arr.end, f"[{nl}{ind}{self._dump(value, ind)}{nl}{base}]"
                    )
                return
            self._apply(arr.end - 1, arr.end - 1, self._dump(value, self._line_indent(arr.start)))
            return
        last = arr.items[-1]
        trailing = last.comma is not None
        p_end = last.comma + 1 if last.comma is not None else last.end
        tail = self._line_tail_end(p_end)
        if tail is None or "\n" not in t[arr.start : arr.end]:
            item = self._dump(value, self._line_indent(last.start), True)
            self._apply(p_end, p_end, f" {item}," if trailing else f", {item}")
            return
        line_start = self._line_start(last.start)
        lead = t[line_start : last.start]
        ind = lead if lead.strip() == "" else self._line_indent(arr.start) + unit
        item = self._dump(value, ind)
        between = t[p_end:tail]
        cr = "\r" if between.endswith("\r") else ""
        between = between.removesuffix("\r")
        self._apply(
            p_end,
            tail,
            f"{'' if trailing else ','}{between}{nl}{ind}{item}{',' if trailing else ''}{cr}",
        )

    def _remove(self, container: Obj | Arr, index: int) -> None:
        t = self._text
        entries: Sequence[Member | Item] = (
            container.members if isinstance(container, Obj) else container.items
        )
        entry = entries[index]
        start = entry.key_start if isinstance(entry, Member) else entry.start
        comma = entry.comma
        end = comma + 1 if comma is not None else entry.end
        is_last = index == len(entries) - 1
        prev = entries[index - 1] if index > 0 else None
        line_start = self._line_start(start)
        alone_before = t[line_start:start].strip() == ""
        tail = self._line_tail_end(end)
        if alone_before and tail is not None:
            # the entry owns its lines: drop them entirely
            cut_end = tail + 1 if tail < len(t) else tail
            if is_last and comma is None and prev is not None and prev.comma is not None:
                # no trailing-comma style: the previous entry loses its comma
                self._apply_two((prev.comma, prev.comma + 1, ""), (line_start, cut_end, ""))
            else:
                self._apply(line_start, cut_end, "")
            return
        # inline entry
        if comma is not None:
            j = end
            while j < len(t) and t[j] in " \t":
                j += 1
            self._apply(start, j, "")
        elif prev is not None and prev.comma is not None:
            self._apply(prev.comma, entry.end, "")
        else:
            self._apply(start, entry.end, "")

    def _apply_two(self, first: tuple[int, int, str], second: tuple[int, int, str]) -> None:
        """Apply two non-overlapping splices (given in original-offset order) at once."""
        (s1, e1, r1), (s2, e2, r2) = first, second
        assert e1 <= s2
        text = self._text[:s1] + r1 + self._text[e1:s2] + r2 + self._text[e2:]
        self._root = self._parse_text(text)
        self._text = text


def _last_member(obj: Obj, key: str) -> Member | None:
    for m in reversed(obj.members):
        if m.key == key:
            return m
    return None


def _nest(rest: KeyPath, value: Any) -> Any:
    """Wrap ``value`` in the dicts needed for the remaining path segments."""
    for seg in reversed(rest):
        if not isinstance(seg, str):
            raise FormatError("cannot create array elements implicitly")
        value = {seg: value}
    return value
