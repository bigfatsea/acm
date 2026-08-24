# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Fault injection tests for Safety Engine (WP3)."""

from pathlib import Path

import pytest

from acm.adapters import PlannedOp
from acm.errors import SafetyBlockedError
from acm.safety import write_changeset
from acm.state import list_snapshots, load_last_write


def test_whitelist_file_violation(tmp_home: Path) -> None:
    """Test write_changeset blocks operations on un-whitelisted files."""
    allowed_file = tmp_home / "allowed.json"
    forbidden_file = tmp_home / "forbidden.json"
    allowed_file.write_text('{"model": "old"}', encoding="utf-8")
    forbidden_file.write_text('{"model": "old"}', encoding="utf-8")

    ops = [PlannedOp(file=forbidden_file, path="model", new="new-model")]

    with pytest.raises(SafetyBlockedError, match="Whitelist violation: file"):
        write_changeset(
            agent_id="test_agent",
            profile_name="daily",
            allowed_paths=[allowed_file],
            allowed_namespaces=["model"],
            ops=ops,
        )

    # Verify forbidden file was NOT touched
    assert forbidden_file.read_text(encoding="utf-8") == '{"model": "old"}'


def test_whitelist_namespace_violation(tmp_home: Path) -> None:
    """Test write_changeset blocks operations outside allowed namespace."""
    target_file = tmp_home / "settings.json"
    target_file.write_text('{"model": "old", "secret_admin_key": "123"}', encoding="utf-8")

    ops = [PlannedOp(file=target_file, path="secret_admin_key", new="hacked")]

    with pytest.raises(SafetyBlockedError, match="Whitelist violation: dot-path"):
        write_changeset(
            agent_id="test_agent",
            profile_name="daily",
            allowed_paths=[target_file],
            allowed_namespaces=["model", "env"],
            ops=ops,
        )

    assert "hacked" not in target_file.read_text(encoding="utf-8")


def test_pre_commit_fingerprint_mismatch(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that external modification between snapshot and commit is blocked."""
    target_file = tmp_home / "settings.json"
    target_file.write_text('{"model": "initial"}', encoding="utf-8")

    monkeypatch.setenv("ACM_TEST_FAULT_PRE_COMMIT_MODIFY", "1")

    ops = [PlannedOp(file=target_file, path="model", new="projected-model")]

    with pytest.raises(SafetyBlockedError, match="Pre-commit fingerprint mismatch"):
        write_changeset(
            agent_id="test_agent",
            profile_name="daily",
            allowed_paths=[target_file],
            allowed_namespaces=["model"],
            ops=ops,
        )


def test_successful_write_and_snapshot(tmp_home: Path) -> None:
    """Test normal successful write creates snapshot and updates last_write."""
    target_file = tmp_home / "settings.json"
    target_file.write_text('{"model": "old", "unmanaged_plugin": "keep"}', encoding="utf-8")

    ops = [PlannedOp(file=target_file, path="model", new="new-model")]

    res = write_changeset(
        agent_id="test_agent",
        profile_name="daily",
        allowed_paths=[target_file],
        allowed_namespaces=["model"],
        ops=ops,
    )

    assert not res.noop
    assert res.backup_id is not None

    # Check file content
    assert '"model": "new-model"' in target_file.read_text(encoding="utf-8")
    assert '"unmanaged_plugin": "keep"' in target_file.read_text(encoding="utf-8")

    # Check snapshot exists
    snapshots = list_snapshots("test_agent")
    assert len(snapshots) == 1
    assert snapshots[0] == res.backup_id

    # Check last_write
    lw = load_last_write("test_agent")
    assert lw is not None
    assert lw.profile == "daily"
    assert (
        lw.fields.get("settings.json::model") == "new-model"
        or lw.fields.get("model") == "new-model"
    )
