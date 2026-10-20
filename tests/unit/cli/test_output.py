from pathlib import Path

from acm.adapters.base import launch_notes
from acm.cli.output import field_lines
from acm.engine.apply import describe_drift
from acm.engine.model import DriftItem, ProjectionWarning
from acm.formats.base import MISSING


def test_a_changed_subtree_prints_only_its_changed_leaves():
    before = {
        "baseUrl": "http://a/v1",
        "apiKey": "sk-secret-value-1",
        "models": [{"id": "m", "ctx": 1}],
    }
    after = {
        "baseUrl": "http://b/v1",
        "apiKey": "sk-secret-value-2",
        "models": [{"id": "m", "ctx": 2}],
    }
    lines = field_lines(("providers", "vmr"), before, after, show_secrets=False)
    assert lines == [
        "providers.vmr.baseUrl: 'http://a/v1' -> 'http://b/v1'",
        "providers.vmr.apiKey: 'sk-...e-1' -> 'sk-...e-2'",
        "providers.vmr.models[0].ctx: 1 -> 2",
    ]


def test_added_keys_lists_of_other_length_and_owned_files():
    assert field_lines(("a",), {"x": 1}, {"x": 1, "y": True}, False) == ["a.y: (absent) -> True"]
    assert field_lines(("l",), [1], [1, 2], False) == ["l: [1] -> [1, 2]"]
    assert field_lines(("k",), 1, True, False) == ["k: 1 -> True"]  # bool is not 1
    f = Path("/h/.acm/owned/codex/catalog.json")
    assert field_lines((), "<file>", "<file>", False, f) == ["catalog.json: replaced"]
    assert field_lines((), MISSING, "<file>", False, f) == ["catalog.json: created"]


def test_drift_on_a_subtree_names_the_leaf():
    f = Path("/h/.pi/agent/models.json")
    text = describe_drift(
        [DriftItem(f, ("providers", "vmr"), {"baseUrl": "x", "n": 1}, {"baseUrl": "y", "n": 1})]
    )
    assert text == f"  {f} providers.vmr.baseUrl: acm wrote 'x', now 'y'"
    assert "deleted since acm wrote it" in describe_drift([DriftItem(f, (), "abc", "-")])


def test_launch_notes_keep_the_field():
    warns = [
        ProjectionWarning("models.m.limit.output", "unknown; wrote 32000", "opencode"),
        ProjectionWarning("api_key", "plain text", "opencode"),
    ]
    assert launch_notes(warns) == ["models.m.limit.output: unknown; wrote 32000"]
