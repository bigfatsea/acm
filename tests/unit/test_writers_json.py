# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for JSON order-preserving editor (WP2)."""

import json
from collections import OrderedDict

from acm.writers.json_editor import (
    NOT_FOUND,
    delete_json_path,
    detect_json_formatting,
    read_json_path,
    set_json_path,
)


def test_detect_json_formatting() -> None:
    """Test indentation, newline, and ascii detection."""
    content_4space = '{\n    "key": "value"\n}\n'
    indent, nl, ascii_flag = detect_json_formatting(content_4space)
    assert indent == 4
    assert nl is True
    assert ascii_flag is True

    content_2space_no_nl = '{\n  "name": "测试"\n}'
    indent, nl, ascii_flag = detect_json_formatting(content_2space_no_nl)
    assert indent == 2
    assert nl is False
    assert ascii_flag is False


def test_read_json_path() -> None:
    """Test reading nested dot-paths from JSON."""
    content = """{
  "model": "claude-3-5-sonnet",
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8800",
    "CUSTOM_ENV": "123"
  },
  "permissions": ["read", "write"]
}"""
    assert read_json_path(content, "model") == "claude-3-5-sonnet"
    assert read_json_path(content, "env.ANTHROPIC_BASE_URL") == "http://localhost:8800"
    assert read_json_path(content, "permissions") == ["read", "write"]
    assert read_json_path(content, "non_existent") is NOT_FOUND
    assert read_json_path(content, "env.non_existent") is NOT_FOUND


def test_set_json_path_preserves_order() -> None:
    """Test setting a path preserves key order and unmanaged fields."""
    content = """{
  "permissions": "all",
  "env": {
    "CUSTOM": "keep_me"
  },
  "model": "old-model",
  "hooks": {
    "on_save": "prettier"
  }
}
"""
    updated = set_json_path(content, "model", "new-model")
    updated = set_json_path(updated, "env.ANTHROPIC_BASE_URL", "http://127.0.0.1:8800")

    # Verify top-level keys are still in order: permissions -> env -> model -> hooks
    data = json.loads(updated, object_pairs_hook=OrderedDict)
    top_keys = list(data.keys())
    assert top_keys == ["permissions", "env", "model", "hooks"]

    # Verify values
    assert read_json_path(updated, "model") == "new-model"
    assert read_json_path(updated, "env.CUSTOM") == "keep_me"
    assert read_json_path(updated, "env.ANTHROPIC_BASE_URL") == "http://127.0.0.1:8800"
    assert read_json_path(updated, "hooks.on_save") == "prettier"


def test_delete_json_path() -> None:
    """Test deleting a path from JSON."""
    content = """{
  "a": 1,
  "b": {
    "c": 2,
    "d": 3
  }
}
"""
    updated = delete_json_path(content, "b.c")
    assert read_json_path(updated, "b.c") is NOT_FOUND
    assert read_json_path(updated, "b.d") == 3
    assert read_json_path(updated, "a") == 1
