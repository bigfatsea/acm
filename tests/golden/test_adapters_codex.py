# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Golden tests for Codex adapter (WP7): Apply, Non-destructive, Rollback."""

import hashlib
from pathlib import Path

import tomlkit
from conftest import make_mock_profile

from acm.adapters import codex
from acm.safety import write_changeset
from acm.state import get_snapshots_dir, load_last_write
from acm.writers.toml_editor import read_toml_path
from acm.writers.tree_diff import tree_diff


def test_codex_golden_abc(tmp_home: Path) -> None:
    """Execute Golden a/b/c assertion suite for Codex."""
    fixture_src = Path(__file__).parent.parent / "fixtures" / "codex" / "config.golden.toml"
    initial_content = fixture_src.read_text(encoding="utf-8")
    initial_sha = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()

    # Setup target file in fake home
    codex_dir = tmp_home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    target_file = codex_dir / "config.toml"
    target_file.write_text(initial_content, encoding="utf-8")

    # 1. Plan operations for profile
    profile = make_mock_profile(model_id="o3-mini-20250131")
    ops, _warnings = codex.plan(profile)
    assert len(ops) >= 3

    # ── Step a: Apply ─────────────────────────────────────────
    res = write_changeset(
        agent_id=codex.AGENT_ID,
        profile_name="daily",
        allowed_paths=codex.config_paths(),
        allowed_namespaces=codex.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop
    assert res.backup_id is not None

    updated_content = target_file.read_text(encoding="utf-8")
    assert read_toml_path(updated_content, "model") == "o3-mini-20250131"
    assert read_toml_path(updated_content, "model_provider") == "mock_p"
    assert read_toml_path(updated_content, "model_providers.mock_p.name") == "mock_p"
    assert (
        read_toml_path(updated_content, "model_providers.mock_p.base_url")
        == "http://localhost:8800"
    )
    assert read_toml_path(updated_content, "model_providers.mock_p.wire_api") == "responses"
    assert read_toml_path(updated_content, "model_providers.mock_p.env_key") == "KEY"

    # ── Step b: Non-destructive assertion ──────────────────────
    assert "# Heavy MCP servers configuration with detailed comments" in updated_content
    assert "# Database MCP server" in updated_content
    assert read_toml_path(updated_content, "mcp_servers.filesystem.command") == "npx"
    assert read_toml_path(updated_content, "features.sandbox") == "workspace"

    parsed_before = tomlkit.parse(initial_content)
    parsed_after = tomlkit.parse(updated_content)
    diffs = tree_diff(dict(parsed_before), dict(parsed_after), codex.managed_namespaces())
    assert diffs == []  # Unmanaged fields (mcp_servers, features) 100% untouched!

    # ── Step c: Rollback ───────────────────────────────────────
    lw = load_last_write(codex.AGENT_ID)
    assert lw is not None
    snap_file = get_snapshots_dir(codex.AGENT_ID) / lw.backup_id / "config.toml"
    assert snap_file.exists()

    # Restore snapshot bytes
    target_file.write_bytes(snap_file.read_bytes())
    restored_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
    assert restored_sha == initial_sha
