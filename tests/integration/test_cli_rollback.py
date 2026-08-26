# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for acm rollback command (WP5b & Code Review Batch 1)."""

from collections.abc import Callable
from pathlib import Path

from conftest import MockAdapter
from typer.testing import CliRunner

from acm.adapters import register_adapter
from acm.cli import cli_app

runner = CliRunner()


def test_rollback_restores_file_and_clears_drift(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test rollback restores pre-write bytes and status is not DRIFTED, allowing subsequent use."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    initial_content = '{\n  "model": "initial-model",\n  "custom": 123\n}\n'
    target_file.write_text(initial_content, encoding="utf-8")

    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    # 1. Apply projection
    res_use1 = runner.invoke(cli_app, ["use", "daily"])
    assert res_use1.exit_code == 0
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")

    # 2. Perform rollback
    res_rb = runner.invoke(cli_app, ["rollback"])
    assert res_rb.exit_code == 0
    assert "Restored settings.json from snapshot" in res_rb.stdout
    assert target_file.read_text(encoding="utf-8") == initial_content

    # 3. Status must NOT be DRIFTED
    res_st = runner.invoke(cli_app, ["status"])
    assert res_st.exit_code == 0
    assert "DRIFTED" not in res_st.stdout

    # 4. Subsequent use without --force must succeed with exit code 0 (no false-positive drift block!)
    res_use2 = runner.invoke(cli_app, ["use", "daily"])
    assert res_use2.exit_code == 0
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")


def test_double_rollback_undo_chain(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test undo-undo rollback restores forward projection."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    initial_content = '{\n  "model": "initial-model"\n}\n'
    target_file.write_text(initial_content, encoding="utf-8")

    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    # 1. Project
    runner.invoke(cli_app, ["use", "daily"])
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")

    # 2. Rollback 1
    runner.invoke(cli_app, ["rollback"])
    assert '"model": "initial-model"' in target_file.read_text(encoding="utf-8")

    # 3. Rollback 2 (undo of rollback 1)
    res_rb2 = runner.invoke(cli_app, ["rollback"])
    assert res_rb2.exit_code == 0
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")


def test_rollback_does_not_claim_unmanaged_user_fields(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """[R-4 Regression] Rollback must not claim ownership of user-owned keys in managed namespaces."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    # User file has a key inside a managed namespace ("env.KEY") that ACM does not manage in this projection
    initial_content = '{\n  "model": "initial-model",\n  "env": {"KEY": "user-original-key"}\n}\n'
    target_file.write_text(initial_content, encoding="utf-8")

    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    # 1. Project
    res_use = runner.invoke(cli_app, ["use", "daily"])
    assert res_use.exit_code == 0

    # 2. Rollback
    res_rb = runner.invoke(cli_app, ["rollback"])
    assert res_rb.exit_code == 0

    # 3. User modifies their own key
    target_file.write_text(
        '{\n  "model": "initial-model",\n  "env": {"KEY": "user-modified-key"}\n}\n',
        encoding="utf-8",
    )

    # 4. Status must NOT report DRIFTED because ACM only managed "model"
    res_st = runner.invoke(cli_app, ["status"])
    assert res_st.exit_code == 0
    assert "DRIFTED" not in res_st.stdout


def test_rollback_dry_run_zero_writes(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """[N-4 Regression] Rollback --dry-run must not restore files or create new snapshots."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    initial_content = '{\n  "model": "initial-model"\n}\n'
    target_file.write_text(initial_content, encoding="utf-8")

    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    # 1. Project
    runner.invoke(cli_app, ["use", "daily"])
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")

    # 2. Dry run rollback
    res_dry = runner.invoke(cli_app, ["rollback", "--dry-run"])
    assert res_dry.exit_code == 0
    assert "Rollback target for" in res_dry.stdout
    assert "Will restore settings.json from snapshot" in res_dry.stdout

    # Target file must still be unchanged ("coding")
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")
