"""Behaviour every format implementation must share (Document contract)."""

import pytest

from acm.core.errors import FormatError
from acm.formats.base import MISSING, empty, parse

SAMPLES = {
    "json": b'{\n  "a": 1,\n  "env": {"X": "1"},\n  "list": [1, 2]\n}\n',
    "jsonc": b'{\n  // top comment\n  "a": 1, // trailing\n  "env": {\n    "X": "1" /* c */\n  },\n  "list": [1, 2],\n}\n',
    "json5": b"{\n  // json5\n  a: 1,\n  'env': {X: '1',},\n  list: [1, 2,],\n}\n",
    "toml": b'# top\na = 1  # keep\nlist = [1, 2]\n\n[env]\nX = "1"\n',
    "yaml": b"# top\na: 1  # keep\nenv:\n  X: '1'\nlist:\n  - 1\n  - 2\n",
}
FORMATS = list(SAMPLES)


@pytest.fixture(params=FORMATS)
def fmt(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def doc_of(fmt):
    return parse(fmt, SAMPLES[fmt])


def test_unmodified_render_is_identical(fmt):
    assert doc_of(fmt).render() == SAMPLES[fmt]


def test_get_and_tree(fmt):
    d = doc_of(fmt)
    assert d.get(("a",)) == 1
    assert d.get(("env", "X")) == "1"
    assert d.get(("list",)) == [1, 2]
    assert d.get(("nope",)) is MISSING
    assert d.get(("env", "nope", "deeper")) is MISSING
    assert d.tree()["env"] == {"X": "1"}


def test_set_existing_changes_only_that_path(fmt):
    d = doc_of(fmt)
    before = d.tree()
    d.set(("a",), 2)
    after = d.tree()
    assert after["a"] == 2
    assert {k: v for k, v in after.items() if k != "a"} == {
        k: v for k, v in before.items() if k != "a"
    }
    assert parse(fmt, d.render()).tree() == after


def test_set_same_value_is_byte_identical(fmt):
    d = doc_of(fmt)
    d.set(("a",), 1)
    d.set(("env", "X"), "1")
    assert d.render() == SAMPLES[fmt]


def test_set_new_top_and_nested_chain(fmt):
    d = doc_of(fmt)
    d.set(("model",), "m1")
    d.set(("deep", "er", "leaf"), True)
    d.set(("env", "Y"), "2")
    t = parse(fmt, d.render()).tree()
    assert t["model"] == "m1"
    assert t["deep"] == {"er": {"leaf": True}}
    assert t["env"] == {"X": "1", "Y": "2"}
    assert t["a"] == 1 and t["list"] == [1, 2]


def test_set_dict_and_list_values(fmt):
    d = doc_of(fmt)
    d.set(("providers", "vmr"), {"baseUrl": "https://h/v1", "models": [{"id": "coding"}], "n": 3})
    t = parse(fmt, d.render()).tree()
    assert t["providers"]["vmr"] == {
        "baseUrl": "https://h/v1",
        "models": [{"id": "coding"}],
        "n": 3,
    }


def test_delete(fmt):
    d = doc_of(fmt)
    d.delete(("a",))
    d.delete(("env", "X"))
    d.delete(("not", "there"))
    t = parse(fmt, d.render()).tree()
    assert "a" not in t
    assert t["env"] == {}
    assert t["list"] == [1, 2]


def test_keys_containing_dots_and_dashes(fmt):
    d = doc_of(fmt)
    d.set(("modelSettings", "claude-opus-4.6", "effortLevel"), "high")
    d.set(("modelSettings", "gpt-4.1", "x"), 1)
    t = parse(fmt, d.render()).tree()
    assert t["modelSettings"]["claude-opus-4.6"] == {"effortLevel": "high"}
    assert d.get(("modelSettings", "gpt-4.1", "x")) == 1


def test_set_through_scalar_is_an_error(fmt):
    d = doc_of(fmt)
    with pytest.raises(FormatError):
        d.set(("a", "child"), 1)


def test_comments_survive_edits(fmt):
    if fmt in ("json",):
        pytest.skip("plain JSON sample has no comments")
    d = doc_of(fmt)
    d.set(("model",), "m")
    d.set(("a",), 5)
    out = d.render().decode()
    marker = {"jsonc": "// top comment", "json5": "// json5", "toml": "# top", "yaml": "# top"}[fmt]
    assert marker in out
    if fmt in ("jsonc", "toml", "yaml"):
        assert {"jsonc": "// trailing", "toml": "# keep", "yaml": "# keep"}[fmt] in out


def test_empty_document_roundtrip(fmt):
    d = empty(fmt)
    assert d.tree() == {}
    d.set(("model",), "x")
    d.set(("env", "K"), "v")
    assert parse(fmt, d.render()).tree() == {"model": "x", "env": {"K": "v"}}


def test_invalid_input_raises_format_error(fmt):
    bad = {
        "json": b'{"a": ',
        "jsonc": b"{ a b }",
        "json5": b"{ 'a': [1, }",
        "toml": b"a = = 1",
        "yaml": b"a: [1, 2",
    }[fmt]
    with pytest.raises(FormatError):
        parse(fmt, bad)


def test_non_utf8_rejected(fmt):
    with pytest.raises(FormatError):
        parse(fmt, b"\xff\xfe\x00bad")
