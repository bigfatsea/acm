# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Integration tests for Pi adapter through CLI commands (WP8)."""

import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from acm.adapters import clear_adapters, pi, register_adapter
from acm.cli import cli_app

runner = CliRunner()


def test_pi_cli_lifecycle_with_orphan_archive(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_yaml: str
) -> None:
    """Test Pi adapter CLI lifecycle including new file creation and orphan archival on rollback."""
    clear_adapters()
    register_adapter(pi)

    make_config(sample_config_yaml)

    # Setup Pi agent dir with settings.json only (models.json absent)
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    settings_file = pi_dir / "settings.json"
    models_file = pi_dir / "models.json"
    settings_file.write_text('{"custom": "setting"}\n', encoding="utf-8")

    assert not models_file.exists()

    # 1. Project profile 'daily'
    res_use = runner.invoke(cli_app, ["use", "daily"])
    assert res_use.exit_code == 0
    assert "Successfully projected profile 'daily' to Pi Agent" in res_use.stdout
    assert models_file.exists()

    # 2. Check status -> SYNCED
    res_st = runner.invoke(cli_app, ["status"])
    assert res_st.exit_code == 0
    assert "SYNCED" in res_st.stdout

    # 3. Rollback without --force should be blocked when files need to be archived
    res_rb_block = runner.invoke(cli_app, ["rollback"])
    assert res_rb_block.exit_code == 2
    normalized_err = " ".join((res_rb_block.stdout + res_rb_block.stderr).split())
    assert "Use --force to confirm" in normalized_err
    assert models_file.exists()

    # 4. Rollback with --force should succeed and archive models.json
    res_rb = runner.invoke(cli_app, ["rollback", "--force"])
    assert res_rb.exit_code == 0
    assert "Archived ACM-created file models.json" in res_rb.stdout
    assert not models_file.exists()  # Original is no longer at models.json

    # Check that archived file exists
    archived_files = list(pi_dir.glob("models.json.acm_orphaned.*"))
    assert len(archived_files) == 1


def test_pi_pool_use_idempotent_and_drift(
    tmp_home: Path, make_config: Callable[[str], Path]
) -> None:
    """End-to-end model pool: use is idempotent, status SYNCED, external member deletion drifts."""
    clear_adapters()
    register_adapter(pi)

    yaml_str = """version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: sk-pool-key
    models:
      coding: {}
      cheap: {}

profiles:
  daily:
    default: coding
    models:
      main: coding
      budget: cheap
"""
    make_config(yaml_str)

    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)

    # 1. First projection creates models.json with both pool members
    res_use = runner.invoke(cli_app, ["use", "daily"])
    assert res_use.exit_code == 0
    models_file = pi_dir / "models.json"
    content = models_file.read_text(encoding="utf-8")
    assert '"name": "main"' in content
    assert '"name": "budget"' in content

    # 2. status -> SYNCED
    res_st = runner.invoke(cli_app, ["status"])
    assert res_st.exit_code == 0
    assert "SYNCED" in res_st.stdout

    # 3. Re-running use is a no-op (idempotent)
    res_use2 = runner.invoke(cli_app, ["use", "daily"])
    assert res_use2.exit_code == 0
    assert "already in desired state (no-op)" in res_use2.stdout

    # 4. External deletion of a pool member is drift, blocked by default
    payload = json.loads(models_file.read_text(encoding="utf-8"))
    payload["providers"]["vmr"]["models"] = [
        m for m in payload["providers"]["vmr"]["models"] if m["name"] != "budget"
    ]
    models_file.write_text(json.dumps(payload), encoding="utf-8")

    res_drift = runner.invoke(cli_app, ["use", "daily"])
    assert res_drift.exit_code == 2


def test_pi_dry_run_and_drift_masking(tmp_home: Path, make_config: Callable[[str], Path]) -> None:
    """[R-2 Regression] Dry-run and drift diffs must mask secrets in nested dictionary structures."""
    clear_adapters()
    register_adapter(pi)

    yaml_str = """version: 3
providers:
  secret_p:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: sk-super-secret-key-1234567890
    models:
      secret-model: {}

profiles:
  daily:
    default: secret-model
    models:
      main: secret-model
"""
    make_config(yaml_str)

    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    settings_file = pi_dir / "settings.json"
    settings_file.write_text('{"defaultProvider": "old"}\n', encoding="utf-8")

    # 1. Dry run must not leak plaintext key
    res_dry = runner.invoke(cli_app, ["use", "daily", "--dry-run"])
    assert res_dry.exit_code == 0
    assert "sk-super-secret-key-1234567890" not in res_dry.stdout
    assert "sk-...890" in res_dry.stdout

    # 2. Write projection
    runner.invoke(cli_app, ["use", "daily"])

    # 3. Tamper models.json
    models_file = pi_dir / "models.json"
    models_file.write_text(
        '{"providers": {"secret_p": {"baseUrl": "http://127.0.0.1:8800/v1", "apiKey": "TAMPERED_SECRET_9876543210"}}}\n',
        encoding="utf-8",
    )

    # 4. Drift block output must not leak unmasked secrets
    res_drift = runner.invoke(cli_app, ["use", "daily"])
    assert res_drift.exit_code == 2
    drift_output = res_drift.stdout + res_drift.stderr
    assert "sk-super-secret-key-1234567890" not in drift_output
    assert "TAMPERED_SECRET_9876543210" not in drift_output
    assert "sk-...890" in drift_output
    assert "TAM...210" in drift_output
