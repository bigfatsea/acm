# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for acm init command (WP5b)."""

from pathlib import Path

from typer.testing import CliRunner

from acm.cli import cli_app
from acm.config import load_config

runner = CliRunner()


def test_init_command_creates_config(tmp_home: Path) -> None:
    """Test init creates ~/.acm/config.toml and state directory."""
    result = runner.invoke(cli_app, ["init", "--force"])
    assert result.exit_code == 0
    assert "Successfully initialized ACM" in result.stdout

    config_path = tmp_home / ".acm" / "config.toml"
    assert config_path.exists()
    cfg = load_config(config_path)
    assert cfg.version == 1

    # Check .gitignore
    gitignore = tmp_home / ".acm" / ".gitignore"
    assert gitignore.exists()
    assert "state/" in gitignore.read_text(encoding="utf-8")


def test_init_dry_run_zero_writes(tmp_home: Path) -> None:
    """Test init --dry-run does not create any files."""
    result = runner.invoke(cli_app, ["init", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry-run mode" in result.stdout
    assert not (tmp_home / ".acm" / "config.toml").exists()
