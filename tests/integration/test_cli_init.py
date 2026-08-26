# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for acm init command (WP5b)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from acm.cli import cli_app
from acm.config import load_config

runner = CliRunner()


def test_init_command_creates_config(tmp_home: Path) -> None:
    """Test init creates ~/.acm/config.yaml and state directory."""
    result = runner.invoke(cli_app, ["init", "--force"])
    assert result.exit_code == 0
    assert "Successfully initialized ACM" in result.stdout

    config_path = tmp_home / ".acm" / "config.yaml"
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
    assert not (tmp_home / ".acm" / "config.yaml").exists()


def test_init_proposal_banner_mentions_yaml(tmp_home: Path) -> None:
    """The proposed Core Config banner names the YAML file being generated."""
    result = runner.invoke(cli_app, ["init", "--dry-run"])
    assert result.exit_code == 0
    assert "Proposed ~/.acm/config.yaml" in result.stdout


def test_init_writes_config_yaml_with_0600(tmp_home: Path) -> None:
    """Generated Core Config file carries owner-only permissions."""
    result = runner.invoke(cli_app, ["init", "--force"])
    assert result.exit_code == 0
    config_path = tmp_home / ".acm" / "config.yaml"
    assert (config_path.stat().st_mode & 0o777) == 0o600


def test_init_auth_required_warns_and_falls_back_to_template(
    tmp_home: Path, fake_vmr_server_factory: Callable[..., str]
) -> None:
    """A VMR gated by api_keys must warn explicitly (never claim 'not running'),
    still complete with a direct-connect template, exit 0, and never leak the key."""
    fake_vmr_server_factory(api_keys=frozenset({"sk-real"}))
    result = runner.invoke(cli_app, ["init", "--force"])
    combined = result.stdout + result.stderr
    assert result.exit_code == 0
    assert "requires authentication" in combined
    assert "not running" not in combined
    assert "sk-real" not in combined

    config_path = tmp_home / ".acm" / "config.yaml"
    cfg = load_config(config_path)
    assert "vmr" not in cfg.providers


def test_init_ok_path_with_valid_vmr_key(
    tmp_home: Path,
    fake_vmr_server_factory: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gated VMR with the correct VMR_KEY still produces a VMR proposal."""
    fake_vmr_server_factory(api_keys=frozenset({"sk-real"}))
    monkeypatch.setenv("VMR_KEY", "sk-real")
    result = runner.invoke(cli_app, ["init", "--force"])
    combined = result.stdout + result.stderr
    assert result.exit_code == 0
    assert "VMR detected" in result.stdout
    assert "sk-real" not in combined

    config_path = tmp_home / ".acm" / "config.yaml"
    cfg = load_config(config_path)
    assert "vmr" in cfg.providers
