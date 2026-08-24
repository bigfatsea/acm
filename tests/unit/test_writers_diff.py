# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for AST / Tree diff utility (WP2)."""

import json

from acm.writers.tree_diff import tree_diff


def test_tree_diff_no_changes() -> None:
    """Test tree diff when trees are identical."""
    obj1 = {"a": 1, "b": {"c": "hello", "d": [1, 2, 3]}}
    obj2 = {"a": 1, "b": {"c": "hello", "d": [1, 2, 3]}}
    assert tree_diff(obj1, obj2, managed_paths=["a"]) == []


def test_tree_diff_managed_changes_ignored() -> None:
    """Test changes to managed paths are ignored by diff."""
    before = {
        "model": "claude-3-opus",
        "env": {"ANTHROPIC_BASE_URL": "http://old", "OTHER": "keep"},
        "plugins": ["git"],
    }
    after = {
        "model": "claude-3-7-sonnet",
        "env": {"ANTHROPIC_BASE_URL": "http://new:8800", "OTHER": "keep"},
        "plugins": ["git"],
    }
    managed = ["model", "env.ANTHROPIC_BASE_URL"]
    diffs = tree_diff(before, after, managed_paths=managed)
    assert diffs == []


def test_tree_diff_unmanaged_changes_detected() -> None:
    """Test unintended mutations to unmanaged fields are detected."""
    before = {
        "model": "claude-3-opus",
        "env": {"ANTHROPIC_BASE_URL": "http://old", "OTHER": "keep"},
        "plugins": ["git"],
    }
    after = {
        "model": "claude-3-7-sonnet",
        "env": {"ANTHROPIC_BASE_URL": "http://new:8800", "OTHER": "corrupted"},
        "plugins": ["git", "extra"],
    }
    managed = ["model", "env.ANTHROPIC_BASE_URL"]
    diffs = tree_diff(before, after, managed_paths=managed)
    assert len(diffs) == 2
    assert any("OTHER" in d for d in diffs)
    assert any("plugins" in d for d in diffs)


def test_tree_diff_numeric_tolerance() -> None:
    """Test int and float numeric equivalence (1 == 1.0)."""
    before = {"temperature": 1}
    after = {"temperature": 1.0}
    assert tree_diff(before, after, managed_paths=[]) == []


def test_tree_diff_json_roundtrip_fidelity() -> None:
    """Test diffing real json payloads."""
    payload_before = json.loads('{"permissions": "admin", "model": "old", "hooks": {"on": true}}')
    payload_after = json.loads('{"permissions": "admin", "model": "new", "hooks": {"on": true}}')
    assert tree_diff(payload_before, payload_after, managed_paths=["model"]) == []
