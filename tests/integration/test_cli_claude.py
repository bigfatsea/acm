# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for Claude Code adapter through CLI commands (WP6)."""

from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from acm.adapters import claude_code, clear_adapters, register_adapter
from acm.cli import cli_app

runner = CliRunner()


def test_claude_code_cli_lifecycle(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_toml: str
) -> None:
    """Test full CLI lifecycle with Claude Code adapter."""
    clear_adapters()
    register_adapter(claude_code)

    make_config(sample_config_toml)

    # Setup Claude Code settings file
    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(
        '{\n  "model": "old",\n  "permissions": "admin"\n}\n', encoding="utf-8"
    )

    # 1. Project profile 'daily'
    res_use = runner.invoke(cli_app, ["use", "daily"])
    assert res_use.exit_code == 0
    assert "Successfully projected profile 'daily' to Claude Code" in res_use.stdout

    # 2. Check status -> SYNCED
    res_st = runner.invoke(cli_app, ["status"])
    assert res_st.exit_code == 0
    assert "SYNCED" in res_st.stdout

    # 3. Simulate external drift
    settings_file.write_text(
        '{\n  "model": "tampered",\n  "permissions": "admin"\n}\n', encoding="utf-8"
    )

    # 4. Check status -> DRIFTED
    res_drift = runner.invoke(cli_app, ["status"])
    assert res_drift.exit_code == 0
    assert "DRIFTED" in res_drift.stdout

    # 5. use without force should be blocked
    res_block = runner.invoke(cli_app, ["use", "direct"])
    assert res_block.exit_code == 2
    assert "Safety Block: external drift detected" in (res_block.stdout + res_block.stderr)

    # 6. use with --force succeeds
    res_force = runner.invoke(cli_app, ["use", "direct", "--force"])
    assert res_force.exit_code == 0
    assert "Successfully projected profile 'direct' to Claude Code" in res_force.stdout

    # 7. rollback restores previous state
    res_rb = runner.invoke(cli_app, ["rollback"])
    assert res_rb.exit_code == 0
    assert "Restored settings.json from snapshot" in res_rb.stdout
