# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Golden tests for Claude Code adapter (WP6): Apply, Non-destructive, Rollback."""

import hashlib
import json
from pathlib import Path

from conftest import make_mock_profile

from acm.adapters import claude_code
from acm.safety import write_changeset
from acm.state import get_snapshots_dir, load_last_write
from acm.writers.json_editor import read_json_path
from acm.writers.tree_diff import tree_diff


def test_claude_code_golden_abc(tmp_home: Path) -> None:
    """Execute Golden a/b/c assertion suite for Claude Code."""
    fixture_src = Path(__file__).parent.parent / "fixtures" / "claude_code" / "settings.golden.json"
    initial_content = fixture_src.read_text(encoding="utf-8")
    initial_sha = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()

    # Setup target file in fake home
    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    target_file = claude_dir / "settings.json"
    target_file.write_text(initial_content, encoding="utf-8")

    # 1. Plan operations for profile
    profile = make_mock_profile(model_id="claude-3-7-sonnet-20250219")
    ops, _warnings = claude_code.plan(profile)
    assert len(ops) >= 3

    # ── Step a: Apply ─────────────────────────────────────────
    res = write_changeset(
        agent_id=claude_code.AGENT_ID,
        profile_name="daily",
        allowed_paths=claude_code.config_paths(),
        allowed_namespaces=claude_code.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop
    assert res.backup_id is not None

    updated_content = target_file.read_text(encoding="utf-8")
    assert read_json_path(updated_content, "model") == "claude-3-7-sonnet-20250219"
    assert read_json_path(updated_content, "env.ANTHROPIC_BASE_URL") == "http://localhost:8800"
    assert read_json_path(updated_content, "env.ANTHROPIC_AUTH_TOKEN") == "mock_key"

    # ── Step b: Non-destructive assertion ──────────────────────
    parsed_before = json.loads(initial_content)
    parsed_after = json.loads(updated_content)
    diffs = tree_diff(parsed_before, parsed_after, claude_code.managed_namespaces())
    assert diffs == []  # Unmanaged fields (permissions, custom env, plugins) 100% untouched!

    assert read_json_path(updated_content, "permissions.allow_read") is True
    assert read_json_path(updated_content, "env.USER_CUSTOM_VAR") == "keep_this_custom_env_val"
    assert read_json_path(updated_content, "enabledPlugins") == ["git", "formatter"]

    # ── Step c: Rollback ───────────────────────────────────────
    lw = load_last_write(claude_code.AGENT_ID)
    assert lw is not None
    snap_file = get_snapshots_dir(claude_code.AGENT_ID) / lw.backup_id / "settings.json"
    assert snap_file.exists()

    # Restore snapshot bytes
    target_file.write_bytes(snap_file.read_bytes())
    restored_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
    assert restored_sha == initial_sha
