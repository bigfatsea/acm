# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for acm status command (WP5b)."""

from collections.abc import Callable
from pathlib import Path

from conftest import MockAdapter
from typer.testing import CliRunner

from acm.adapters import register_adapter
from acm.cli import cli_app

runner = CliRunner()


def test_status_uninitialized_fails(tmp_home: Path) -> None:
    """Test status fails with exit code 1 if config.yaml does not exist."""
    result = runner.invoke(cli_app, ["status"])
    assert result.exit_code == 1
    normalized = " ".join((result.stdout + result.stderr).split())
    assert "Run 'acm init' first" in normalized


def test_status_display_table(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test status outputs a table with registered adapter state."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "agent_test.json"
    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    result = runner.invoke(cli_app, ["status"])
    assert result.exit_code == 0
    assert "ACM Agent Status" in result.stdout
    assert "Mock Agent" in result.stdout
