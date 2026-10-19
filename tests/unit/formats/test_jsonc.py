"""JSON/JSONC/JSON5 editor: byte preservation, style fidelity, JSON5 syntax."""

import math

import pytest

from acm.core.errors import FormatError
from acm.formats.base import MISSING
from acm.formats.jsonc import JsoncDocument


def doc(text: str, fmt: str = "jsonc") -> JsoncDocument:
    return JsoncDocument.parse(fmt, text.encode())


def out(d: JsoncDocument) -> str:
    return d.render().decode()


# ------------------------------------------------------------------ parsing


def test_json5_syntax_values():
    d = doc(
        """{
  unquoted: 'single \\' quote',
  $dollar_1: "x\\u0041\\x42\\n\\
cont",
  hex: 0xFF, neg: -0x10, plus: +5, float: .5, exp: 1e3, trail: 1.,
  inf: Infinity, ninf: -Infinity, nan: NaN,
  t: true, f: false, n: null,
  arr: [1, 'two', [3,], {four: 4},],
}""",
        "json5",
    )
    t = d.tree()
    assert t["unquoted"] == "single ' quote"
    assert t["$dollar_1"] == "xAB\ncont"
    assert (t["hex"], t["neg"], t["plus"], t["float"], t["exp"], t["trail"]) == (
        255,
        -16,
        5,
        0.5,
        1000.0,
        1.0,
    )
    assert t["inf"] == math.inf and t["ninf"] == -math.inf and math.isnan(t["nan"])
    assert (t["t"], t["f"], t["n"]) == (True, False, None)
    assert t["arr"] == [1, "two", [3], {"four": 4}]


def test_surrogate_pair_escape():
    assert doc('{"e": "\\ud83d\\ude00"}').tree() == {"e": "😀"}


@pytest.mark.parametrize(
    "bad",
    [
        '{"a": 1,, }',
        '{"a" 1}',
        "{",
        '{"a": "x',
        "[1]",
        '"s"',
        '{"a": 1} extra',
        '{"a": /* open}',
        '{"a": nul}',
    ],
)
def test_parse_errors_have_position(bad):
    with pytest.raises(FormatError):
        doc(bad)


def test_error_message_has_line_and_column():
    with pytest.raises(FormatError, match=r"line 3, column"):
        doc('{\n  "a": 1,\n  "b" 2\n}')


def test_deep_nesting_rejected_not_crashed():
    with pytest.raises(FormatError, match="nesting"):
        doc("{" + '"a":{' * 300 + "}" * 301)


# -------------------------------------------------------- byte preservation


ORIGINAL = """\
{
  // keep this comment
  "model": "old", // inline note
  "env": {
    "A": "1",   // aligned
    "B": "2"
  },
  /* block */ "list": [1, 2, 3],
  'single': 'q',
  unq: 1,
}
"""


def test_replace_existing_value_touches_only_that_span():
    d = doc(ORIGINAL)
    d.set(("model",), "new")
    expected = ORIGINAL.replace('"old"', '"new"')
    assert out(d) == expected


def test_replace_scalar_with_container_and_back():
    d = doc(ORIGINAL)
    d.set(("model",), {"a": 1})
    assert d.get(("model",)) == {"a": 1}
    assert "// inline note" in out(d)
    d.set(("model",), "x")
    assert out(d) == ORIGINAL.replace('"old"', '"x"')


def test_insert_member_multiline_keeps_comments_and_style():
    d = doc(ORIGINAL)
    d.set(("env", "C"), "3")
    text = out(d)
    assert '    "C": "3"\n' in text
    assert '"B": "2",\n' in text  # comma added after the previous last member
    for c in ("// keep this comment", "// inline note", "// aligned", "/* block */"):
        assert c in text
    # outside of the env object nothing moved
    assert text.startswith(ORIGINAL[: ORIGINAL.index('"B": "2"')])


def test_insert_member_after_trailing_comment_stays_on_its_own_line():
    d = doc('{\n  "a": 1 // note\n}\n')
    d.set(("b",), 2)
    assert out(d) == '{\n  "a": 1, // note\n  "b": 2\n}\n'


def test_insert_respects_trailing_comma_style():
    d = doc('{\n  "a": 1,\n}\n')
    d.set(("b",), 2)
    assert out(d) == '{\n  "a": 1,\n  "b": 2,\n}\n'


def test_insert_into_inline_object():
    d = doc('{"a": 1, "env": {"X": 1}}')
    d.set(("env", "Y"), 2)
    assert out(d) == '{"a": 1, "env": {"X": 1, "Y": 2}}'
    d.set(("z",), [1, 2])
    assert d.tree()["z"] == [1, 2]
    assert "\n" not in out(d).strip()


def test_insert_into_empty_objects():
    d = doc('{\n  "env": {},\n  "x": {\n  }\n}\n')
    d.set(("env", "K"), "v")
    d.set(("x", "K"), "w")
    assert out(d) == '{\n  "env": {\n    "K": "v"\n  },\n  "x": {\n    "K": "w"\n  }\n}\n'


def test_indent_unit_follows_the_file():
    d4 = doc('{\n    "a": {\n        "b": 1\n    }\n}\n')
    d4.set(("a", "c"), {"d": 1})
    assert '        "c": {\n            "d": 1\n        }' in out(d4)
    dt = doc('{\n\t"a": 1\n}\n')
    dt.set(("n", "m"), 1)
    assert '\n\t"n": {\n\t\t"m": 1\n\t}' in out(dt)


def test_crlf_preserved_on_insert_and_delete():
    text = '{\r\n  "a": 1, // c\r\n  "b": 2\r\n}\r\n'
    d = doc(text)
    d.set(("c",), 3)
    s = out(d)
    assert "\r\n" in s and "\n" not in s.replace("\r\n", "")
    d.delete(("a",))
    s = out(d)
    assert "\n" not in s.replace("\r\n", "") and '"a"' not in s


def test_bom_preserved():
    data = b"\xef\xbb\xbf" + b'{"a": 1}\n'
    d = JsoncDocument.parse("json", data)
    d.set(("a",), 2)
    assert d.render().startswith(b"\xef\xbb\xbf")


def test_empty_file_becomes_object():
    d = doc("   \n")
    d.set(("a",), 1)
    assert d.tree() == {"a": 1}
    assert out(d).startswith("{")


def test_array_insert_and_delete():
    d = doc('{"l": [1, 2]}')
    d.set(("l", 2), 3)
    assert d.get(("l",)) == [1, 2, 3]
    d.delete(("l", 0))
    assert d.get(("l",)) == [2, 3]
    with pytest.raises(FormatError):
        d.set(("l", 9), 1)
    m = doc('{\n  "l": [\n    1,\n    2\n  ]\n}\n')
    m.set(("l", 2), 3)
    assert out(m) == '{\n  "l": [\n    1,\n    2,\n    3\n  ]\n}\n'


def test_null_intermediate_is_replaced():
    d = doc('{"env": null}')
    d.set(("env", "K"), "v")
    assert d.tree() == {"env": {"K": "v"}}


def test_set_under_scalar_or_root_errors():
    d = doc('{"a": "s"}')
    with pytest.raises(FormatError):
        d.set(("a", "b"), 1)
    with pytest.raises(FormatError):
        d.set((), {})
    with pytest.raises(FormatError):
        d.delete(())


def test_cannot_serialise_non_finite_or_unknown():
    d = doc("{}")
    with pytest.raises(FormatError):
        d.set(("x",), math.inf)
    with pytest.raises(FormatError):
        d.set(("x",), object())


# ----------------------------------------------------------------- deletion


def test_delete_member_removes_its_lines_only():
    d = doc(ORIGINAL)
    d.delete(("env", "A"))
    s = out(d)
    assert '"A"' not in s
    assert "// aligned" not in s  # the comment lived on the deleted line
    assert '"B": "2"' in s and "// keep this comment" in s


def test_delete_last_member_without_trailing_comma_fixes_previous_comma():
    d = doc('{\n  "a": 1,\n  "b": 2\n}\n')
    d.delete(("b",))
    assert out(d) == '{\n  "a": 1\n}\n'


def test_delete_last_member_with_trailing_comma_style():
    d = doc('{\n  "a": 1,\n  "b": 2,\n}\n')
    d.delete(("b",))
    assert out(d) == '{\n  "a": 1,\n}\n'


def test_delete_inline_members():
    d = doc('{"a": 1, "b": 2, "c": 3}')
    d.delete(("b",))
    assert out(d) == '{"a": 1, "c": 3}'
    d.delete(("c",))
    assert out(d) == '{"a": 1 }' or out(d) == '{"a": 1}'
    d.delete(("a",))
    assert d.tree() == {}


def test_delete_multiline_value_member():
    d = doc('{\n  "a": 1,\n  "env": {\n    "X": 1\n  },\n  "z": 2\n}\n')
    d.delete(("env",))
    assert out(d) == '{\n  "a": 1,\n  "z": 2\n}\n'


def test_delete_missing_is_noop_and_get_missing():
    d = doc(ORIGINAL)
    d.delete(("nope",))
    d.delete(("env", "nope", "x"))
    assert out(d) == ORIGINAL
    assert d.get(("env", "nope")) is MISSING


def test_duplicate_keys_last_wins_and_delete_removes_all():
    d = doc('{"a": 1, "a": 2}')
    assert d.get(("a",)) == 2
    d.delete(("a",))
    assert d.tree() == {}
