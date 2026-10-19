"""Property tests: random documents, random styles/comments, random edit sequences."""

import random
import re
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from acm.core.errors import FormatError
from acm.formats.base import MISSING, parse
from acm.formats.jsonc import JsoncDocument

KEY = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_.-]{0,6}", fullmatch=True)
SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-1000, 1000),
    st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
    st.text(alphabet="abc XYZ019-_./:'\"\\", max_size=8),
)
VALUE = st.recursive(
    SCALAR,
    lambda c: st.one_of(st.lists(c, max_size=3), st.dictionaries(KEY, c, max_size=3)),
    max_leaves=8,
)
MODEL = st.dictionaries(KEY, VALUE, max_size=4)
PATH = st.lists(KEY, min_size=1, max_size=3).map(tuple)


# ------------------------------------------------------- random JSON5 writer


def write_json5(model: dict[str, Any], seed: int, trailing: bool, unit: str, comments: bool) -> str:
    rnd = random.Random(seed)

    def c() -> str:
        return f"// c{rnd.randrange(10**6)}" if comments and rnd.random() < 0.4 else ""

    def key(k: str) -> str:
        if re.fullmatch(r"[A-Za-z_]\w*", k) and rnd.random() < 0.4:
            return k
        return f'"{k}"'

    def string(s: str) -> str:
        if "'" not in s and '"' not in s and "\\" not in s and rnd.random() < 0.3:
            return f"'{s}'"
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def val(v: Any, depth: int) -> str:
        pad = unit * depth
        if isinstance(v, dict):
            if not v:
                return "{}"
            if rnd.random() < 0.25 and not comments:
                return "{" + ", ".join(f"{key(k)}: {val(x, depth + 1)}" for k, x in v.items()) + "}"
            lines = []
            items = list(v.items())
            for i, (k, x) in enumerate(items):
                comma = "," if (i < len(items) - 1 or trailing) else ""
                note = c()
                lines.append(
                    f"{pad}{unit}{key(k)}: {val(x, depth + 1)}{comma}{(' ' + note) if note else ''}"
                )
            return "{\n" + "\n".join(lines) + f"\n{pad}}}"
        if isinstance(v, list):
            if not v:
                return "[]"
            if all(not isinstance(x, (dict, list)) for x in v) and rnd.random() < 0.5:
                return "[" + ", ".join(val(x, depth + 1) for x in v) + "]"
            lines = []
            for i, x in enumerate(v):
                comma = "," if (i < len(v) - 1 or trailing) else ""
                lines.append(f"{pad}{unit}{val(x, depth + 1)}{comma}")
            return "[\n" + "\n".join(lines) + f"\n{pad}]"
        if isinstance(v, str):
            return string(v)
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        return repr(v)

    head = f"// header {rnd.randrange(10**6)}\n" if comments else ""
    return head + val(model, 0) + "\n"


def model_set(m: dict[str, Any], path: tuple[str, ...], value: Any) -> bool:
    """Mirror of Document.set; returns False when the document must refuse."""
    cur = m
    for seg in path[:-1]:
        nxt = cur.get(seg, MISSING)
        if nxt is MISSING or nxt is None:
            cur[seg] = {}
            cur = cur[seg]
        elif isinstance(nxt, dict):
            cur = nxt
        else:
            return False
    cur[path[-1]] = value
    return True


def model_delete(m: dict[str, Any], path: tuple[str, ...]) -> None:
    cur: Any = m
    for seg in path[:-1]:
        cur = cur.get(seg) if isinstance(cur, dict) else None
        if not isinstance(cur, dict):
            return
    if isinstance(cur, dict):
        cur.pop(path[-1], None)


def comments_of(text: str) -> list[str]:
    return re.findall(r"// c\d+|// header \d+", text)


def structure_ok(model: Any) -> bool:
    return isinstance(model, dict)


# ------------------------------------------------------------------- tests

OPS = st.lists(st.tuples(st.sampled_from(["set", "delete"]), PATH, VALUE), min_size=1, max_size=6)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    model=MODEL,
    seed=st.integers(0, 10**6),
    trailing=st.booleans(),
    unit=st.sampled_from(["  ", "    ", "\t"]),
    comments=st.booleans(),
    ops=OPS,
)
def test_random_edit_sequences_match_model_and_keep_comments(
    model, seed, trailing, unit, comments, ops
):
    import copy

    text = write_json5(model, seed, trailing, unit, comments)
    doc = JsoncDocument.parse("json5", text.encode())
    assert doc.tree() == model  # the writer and the parser agree
    assert doc.render().decode() == text
    expected = copy.deepcopy(model)
    for kind, path, value in ops:
        before_comments = set(comments_of(doc.render().decode()))
        target = doc.get(path)
        if kind == "set":
            trial = copy.deepcopy(expected)
            if model_set(trial, path, value):
                doc.set(path, value)
                expected = trial
            else:
                with pytest.raises(FormatError):
                    doc.set(path, value)
        else:
            doc.delete(path)
            model_delete(expected, path)
        after_comments = set(comments_of(doc.render().decode()))
        # replacing or deleting a container legitimately drops comments inside it;
        # anything else (missing target / scalar target / insertion) must keep every comment
        if kind == "set" and (target is MISSING or not isinstance(target, (dict, list))):
            assert before_comments <= after_comments
        assert doc.tree() == expected
        assert JsoncDocument.parse("json5", doc.render()).tree() == expected


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(model=MODEL, seed=st.integers(0, 10**6), comments=st.booleans(), path=PATH, value=SCALAR)
def test_scalar_replacement_only_changes_the_value_span(model, seed, comments, path, value):
    text = write_json5(model, seed, True, "  ", comments)
    doc = JsoncDocument.parse("json5", text.encode())
    existing = doc.get(path)
    if existing is MISSING or isinstance(existing, (dict, list)):
        return
    doc.set(path, value)
    new = doc.render().decode()
    pre = 0
    while pre < min(len(text), len(new)) and text[pre] == new[pre]:
        pre += 1
    suf = 0
    while suf < min(len(text), len(new)) - pre and text[-1 - suf] == new[-1 - suf]:
        suf += 1
    # everything except one contiguous span is identical, and the span is short (one value)
    assert len(text) - pre - suf <= len(repr(existing)) + 4 or text == new


@settings(max_examples=150, deadline=None)
@given(model=MODEL, ops=OPS)
def test_json_unmodified_and_noop_set_are_byte_identical(model, ops):
    text = write_json5(model, 1, False, "  ", True)
    doc = JsoncDocument.parse("jsonc", text.encode())
    assert doc.render().decode() == text
    for _, path, _ in ops:
        cur = doc.get(path)
        if cur is not MISSING:
            doc.set(path, cur)
    assert doc.render().decode() == text


# ----------------------------------------------------------- TOML / YAML

TKEY = st.from_regex(r"[a-z][a-z0-9_-]{0,6}", fullmatch=True)
TSCALAR = st.one_of(
    st.booleans(),
    st.integers(-1000, 1000),
    st.text(alphabet="abc XYZ019-_./:", min_size=0, max_size=8),
)
TVALUE = st.recursive(
    TSCALAR,
    lambda c: st.one_of(st.lists(TSCALAR, max_size=3), st.dictionaries(TKEY, c, max_size=3)),
    max_leaves=6,
)
TMODEL = st.dictionaries(TKEY, TVALUE, max_size=4)
TPATH = st.lists(TKEY, min_size=1, max_size=3).map(tuple)
TOPS = st.lists(
    st.tuples(st.sampled_from(["set", "delete"]), TPATH, TVALUE), min_size=1, max_size=5
)


def _dump_toml(model: dict[str, Any]) -> bytes:
    import tomlkit

    return tomlkit.dumps(model).encode()


def _dump_yaml(model: dict[str, Any]) -> bytes:
    from io import StringIO

    from ruamel.yaml import YAML

    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = StringIO()
    y.dump(model, buf)
    return buf.getvalue().encode() if model else b""


@pytest.mark.parametrize(("fmt", "dump"), [("toml", _dump_toml), ("yaml", _dump_yaml)])
@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(model=TMODEL, ops=TOPS)
def test_toml_yaml_random_edits_match_model(fmt, dump, model, ops):
    import copy

    data = dump(model)
    doc = parse(fmt, data)
    assert doc.tree() == model
    assert doc.render() == data
    expected = copy.deepcopy(model)
    for kind, path, value in ops:
        if kind == "set":
            trial = copy.deepcopy(expected)
            if not model_set(trial, path, value):
                with pytest.raises(FormatError):
                    doc.set(path, value)
                continue
            doc.set(path, value)
            expected = trial
        else:
            doc.delete(path)
            model_delete(expected, path)
        assert doc.tree() == expected
        assert parse(fmt, doc.render()).tree() == expected
