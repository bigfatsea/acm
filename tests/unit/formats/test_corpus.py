"""Real-shaped configs for the tier-1 agents survive edits."""

from pathlib import Path

import pytest

from acm.formats.base import MISSING, changed_paths, parse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
EXT = {".json": "json", ".jsonc": "jsonc", ".json5": "json5", ".toml": "toml", ".yaml": "yaml"}
FILES = sorted(p for p in FIXTURES.rglob("*") if p.suffix in EXT)


def ids(p: Path) -> str:
    return f"{p.parent.name}/{p.name}"


def test_corpus_is_not_empty():
    assert len(FILES) >= 7


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_roundtrip_is_byte_identical(path: Path):
    data = path.read_bytes()
    assert parse(EXT[path.suffix], data).render() == data


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_noop_sets_are_byte_identical(path: Path):
    data = path.read_bytes()
    d = parse(EXT[path.suffix], data)
    for k, v in d.tree().items():
        d.set((k,), v)
    assert d.render() == data


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_adding_a_managed_looking_key_changes_nothing_else(path: Path):
    fmt = EXT[path.suffix]
    data = path.read_bytes()
    d = parse(fmt, data)
    before = d.tree()
    d.set(("acm_probe", "nested.key", "leaf"), "v")
    d.set(("acm_top",), 1)
    after = parse(fmt, d.render()).tree()
    changed = set(changed_paths(before, after))
    assert changed <= {("acm_probe",), ("acm_top",)}
    assert after["acm_probe"] == {"nested.key": {"leaf": "v"}}


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_every_existing_scalar_can_be_changed_in_place(path: Path):
    fmt = EXT[path.suffix]
    data = path.read_bytes()
    base = parse(fmt, data).tree()

    def scalars(node, prefix=()):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from scalars(v, (*prefix, k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from scalars(v, (*prefix, i))
        elif isinstance(node, str):
            yield prefix

    n = 0
    for p in scalars(base):
        d = parse(fmt, data)
        d.set(p, "CHANGED")
        after = parse(fmt, d.render()).tree()
        assert set(changed_paths(base, after)) == {p}, p
        n += 1
    assert n > 0


@pytest.mark.parametrize(
    "path", [p for p in FILES if p.suffix in (".json", ".jsonc", ".json5")], ids=ids
)
def test_insert_then_delete_restores_json_text_exactly(path: Path):
    data = path.read_bytes()
    d = parse(EXT[path.suffix], data)
    keys = list(d.tree())
    d.set(("zz_new",), {"a": 1})
    d.delete(("zz_new",))
    assert d.render() == data, f"after add/delete of a top-level key in {keys}"
    first = keys[0]
    sub = d.get((first,))
    if isinstance(sub, dict):
        d.set((first, "zz_inner"), "x")
        d.delete((first, "zz_inner"))
        assert d.render() == data


@pytest.mark.parametrize("path", FILES, ids=ids)
def test_delete_of_each_top_level_key_keeps_the_rest(path: Path):
    fmt = EXT[path.suffix]
    data = path.read_bytes()
    base = parse(fmt, data).tree()
    for k in base:
        d = parse(fmt, data)
        d.delete((k,))
        after = parse(fmt, d.render()).tree()
        assert after == {kk: v for kk, v in base.items() if kk != k}
        assert d.get((k,)) is MISSING
