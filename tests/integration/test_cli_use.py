# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for acm use command (WP5b)."""

from collections.abc import Callable
from pathlib import Path

from conftest import MockAdapter
from typer.testing import CliRunner

from acm.adapters import register_adapter
from acm.cli import cli_app
from acm.state import read_active

runner = CliRunner()


def test_use_uninitialized_fails(tmp_home: Path) -> None:
    """Test use fails with exit code 1 if config.yaml does not exist."""
    result = runner.invoke(cli_app, ["use", "daily"])
    assert result.exit_code == 1
    normalized = " ".join((result.stdout + result.stderr).split())
    assert "Run 'acm init' first" in normalized


def test_use_unknown_profile(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test use fails with exit code 4 if profile is not defined."""
    make_config(sample_config_yaml)
    result = runner.invoke(cli_app, ["use", "non_existent_profile"])
    assert result.exit_code == 4


def test_use_targeted_agent_not_detected_exits_4(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test use fails with exit code 4 when a specifically targeted agent is not installed."""
    make_config(sample_config_yaml)
    target_file = tmp_home / "settings.json"
    adapter = MockAdapter(target_file, detected=False)
    register_adapter(adapter)

    result = runner.invoke(cli_app, ["use", "daily", "mock_agent"])
    assert result.exit_code == 4
    assert "not installed or not detected" in (result.stdout + result.stderr)


def test_use_successful_projection(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test successful projection updates file and sets active profile."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    target_file.write_text('{"model": "old"}', encoding="utf-8")
    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    result = runner.invoke(cli_app, ["use", "daily"])
    assert result.exit_code == 0
    assert "Successfully projected profile 'daily'" in result.stdout
    assert read_active() == "daily"
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")


def test_use_drift_blocks_without_force(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test use blocks with exit code 2 when external drift is detected."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    target_file.write_text('{"model": "old"}', encoding="utf-8")
    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    # First projection
    runner.invoke(cli_app, ["use", "daily"])

    # Simulate external drift by tampering file
    target_file.write_text('{"model": "tampered"}', encoding="utf-8")

    # Second projection with different model in profile 'direct'
    result = runner.invoke(cli_app, ["use", "direct"])
    assert result.exit_code == 2
    assert "Safety Block: external drift detected" in (result.stdout + result.stderr)

    # With --force it should succeed
    result_force = runner.invoke(cli_app, ["use", "direct", "--force"])
    assert result_force.exit_code == 0
    assert "Successfully projected profile 'direct'" in result_force.stdout


def test_use_corrupted_config_blocks_with_exit_code_2(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test use blocks with exit code 2 when agent configuration syntax is corrupted."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    target_file.write_text("{corrupted json syntax!", encoding="utf-8")
    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    result = runner.invoke(cli_app, ["use", "daily"])
    assert result.exit_code == 2
    assert "Safety Block: agent configuration file is corrupted" in (result.stdout + result.stderr)

    # With --force it overwrites/repairs
    result_force = runner.invoke(cli_app, ["use", "daily", "--force"])
    assert result_force.exit_code == 0
    assert '"model": "coding"' in target_file.read_text(encoding="utf-8")


def test_use_drift_matching_desired_state_is_noop_exit_0(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """[E3/M-02 Regression] When external drift changes a field to equal desired state, use is no-op exit 0 without --force."""
    make_config(sample_config_yaml)

    target_file = tmp_home / "settings.json"
    target_file.write_text('{"model": "old"}', encoding="utf-8")
    adapter = MockAdapter(target_file, detected=True)
    register_adapter(adapter)

    # 1. Project profile 'daily' (model -> "coding")
    res1 = runner.invoke(cli_app, ["use", "daily"])
    assert res1.exit_code == 0

    # 2. Project profile 'direct' (model -> "claude-3-7-sonnet-20250219")
    res2 = runner.invoke(cli_app, ["use", "direct"])
    assert res2.exit_code == 0

    # 3. User externally tampers file back to "coding" (matches profile 'daily' desired state)
    target_file.write_text('{"model": "coding"}', encoding="utf-8")

    # 4. Running 'use daily' must detect drift from last_write ('direct'), but see that all fields match desired -> no-op exit 0
    res3 = runner.invoke(cli_app, ["use", "daily"])
    assert res3.exit_code == 0
    normalized_out = " ".join((res3.stdout + res3.stderr).split())
    assert "already match desired state (no-op)" in normalized_out


def test_use_pool_only_profile_leaves_settings_untouched(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Registration-only profile (no default): Pi gets members registered, defaults untouched.

    Uses the real pi adapter via the full write pipeline.
    """
    pool_only_yaml = """version: 2

providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY:-sk-test-mock-key}"
    models:
      coding: {}
      cheap: {}

profiles:
  reg:
    models:
      coder: coding
      fast: cheap
"""
    make_config(pool_only_yaml)
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    settings_file = pi_dir / "settings.json"
    settings_before = '{"defaultProvider": "user_own", "defaultModel": "user-model"}'
    settings_file.write_text(settings_before, encoding="utf-8")

    result = runner.invoke(cli_app, ["use", "reg"])
    assert result.exit_code == 0
    assert read_active() == "reg"

    # Pool registered into models.json...
    import json

    models = json.loads((pi_dir / "models.json").read_text())
    assert models["providers"]["vmr"]["baseUrl"] == "http://127.0.0.1:8800/v1"

    # ...while user-owned defaults are byte-identical.
    assert settings_file.read_text(encoding="utf-8") == settings_before
