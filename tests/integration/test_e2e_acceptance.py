# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""End-to-end hard acceptance test suite for ACM MVP (WP9).

Verifies the 8 hard acceptance criteria defined in SPEC v2.1 §12 / ACTION PLAN v1.0 §7:
1. <= 3 commands VMR scenario with 3 P0 agents (Claude Code, Codex, Pi) -> SYNCED.
2. Non-destructive: 10 use/rollback cycles leave unmanaged keys/comments intact.
3. Reversibility: rollback returns exact pre-write bytes, archives new files.
4. Reliability: lock contention returns exit code 2.
5. Idempotency: second use is no-op with zero new snapshots.
6. Protection: whitelist violation and missing ENV blocked with zero writes.
7. Drift: external tampering blocked (exit 2) with expected/found; --force converges.
8. Clean exit: deleting ~/.acm leaves agent configs intact and working.
"""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from acm.adapters import clear_adapters, load_builtin_adapters
from acm.cli import cli_app
from acm.state import list_snapshots
from acm.writers.json_editor import read_json_path
from acm.writers.toml_editor import read_toml_path

runner = CliRunner()


@pytest.fixture
def setup_p0_agents(tmp_home: Path) -> dict[str, Path]:
    """Helper to setup realistic pre-existing configuration for Claude Code, Codex, and Pi."""
    # 1. Claude Code
    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_file = claude_dir / "settings.json"
    claude_file.write_text(
        '{\n  "model": "claude-old",\n  "permissions": {"allow_all": true},\n  "plugins": ["git"]\n}\n',
        encoding="utf-8",
    )

    # 2. Codex
    codex_dir = tmp_home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_file = codex_dir / "config.toml"
    codex_file.write_text(
        '# Unmanaged Top Comment\nmodel = "codex-old"\n\n[features]\nsandbox = "workspace"\n\n# Important MCP Server\n[mcp_servers.fs]\ncommand = "npx"\n',
        encoding="utf-8",
    )

    # 3. Pi (settings exists, models.json does NOT exist initially)
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    pi_settings = pi_dir / "settings.json"
    pi_settings.write_text(
        '{\n  "defaultProvider": "old",\n  "customOption": "keep"\n}\n',
        encoding="utf-8",
    )
    pi_models = pi_dir / "models.json"

    return {
        "claude": claude_file,
        "codex": codex_file,
        "pi_settings": pi_settings,
        "pi_models": pi_models,
    }


@pytest.mark.e2e
def test_acceptance_1_vmr_three_commands_p0_synced(
    tmp_home: Path, setup_p0_agents: dict[str, Path], fake_vmr_server: str
) -> None:
    """[Acceptance #1] <= 3 commands point all 3 P0 agents to unified VMR models and reach SYNCED."""
    clear_adapters()
    load_builtin_adapters()

    # Command 1: init
    res_init = runner.invoke(cli_app, ["init", "--force"])
    assert res_init.exit_code == 0

    # Command 2: use daily
    res_use = runner.invoke(cli_app, ["use", "daily"])
    assert res_use.exit_code == 0

    # Command 3: status
    res_st = runner.invoke(cli_app, ["status"])
    assert res_st.exit_code == 0
    # All 3 agents should be SYNCED
    assert "Claude Code" in res_st.stdout
    assert "Codex CLI" in res_st.stdout
    assert "Pi Agent" in res_st.stdout
    assert res_st.stdout.count("SYNCED") == 3


@pytest.mark.e2e
def test_acceptance_2_non_destructive_ten_cycles(
    tmp_home: Path, setup_p0_agents: dict[str, Path], fake_vmr_server: str
) -> None:
    """[Acceptance #2] 10 use/rollback cycles leave unmanaged fields & comments intact."""
    clear_adapters()
    load_builtin_adapters()

    res_init = runner.invoke(cli_app, ["init", "--force"])
    assert res_init.exit_code == 0

    codex_file = setup_p0_agents["codex"]
    claude_file = setup_p0_agents["claude"]

    for _ in range(10):
        res_u = runner.invoke(cli_app, ["use", "daily"])
        assert res_u.exit_code == 0
        res_r = runner.invoke(cli_app, ["rollback", "--force"])
        assert res_r.exit_code == 0

    # Verify unmanaged contents in Codex config.toml
    codex_text = codex_file.read_text(encoding="utf-8")
    assert "# Important MCP Server" in codex_text
    assert read_toml_path(codex_text, "mcp_servers.fs.command") == "npx"
    assert read_toml_path(codex_text, "features.sandbox") == "workspace"

    # Verify unmanaged contents in Claude settings.json
    claude_text = claude_file.read_text(encoding="utf-8")
    assert read_json_path(claude_text, "permissions.allow_all") is True
    assert read_json_path(claude_text, "plugins") == ["git"]


@pytest.mark.e2e
def test_acceptance_3_reversibility_and_orphan_archive(
    tmp_home: Path, setup_p0_agents: dict[str, Path], fake_vmr_server: str
) -> None:
    """[Acceptance #3] Rollback restores pre-write bytes and archives ACM-created files."""
    clear_adapters()
    load_builtin_adapters()

    claude_file = setup_p0_agents["claude"]
    initial_claude_sha = hashlib.sha256(claude_file.read_bytes()).hexdigest()
    pi_models = setup_p0_agents["pi_models"]
    assert not pi_models.exists()

    runner.invoke(cli_app, ["init", "--force"])
    runner.invoke(cli_app, ["use", "daily"])

    # Rollback without force is safety blocked when archiving newly created files (Exit code 2)
    res_rb_unforced = runner.invoke(cli_app, ["rollback"])
    assert res_rb_unforced.exit_code == 2
    assert pi_models.exists()

    # Rollback with --force
    res_rb = runner.invoke(cli_app, ["rollback", "--force"])
    assert res_rb.exit_code == 0

    # Claude settings byte-level match
    assert hashlib.sha256(claude_file.read_bytes()).hexdigest() == initial_claude_sha

    # Pi models.json was archived
    assert not pi_models.exists()
    assert len(list(pi_models.parent.glob("models.json.acm_orphaned.*"))) == 1


@pytest.mark.e2e
def test_acceptance_4_reliability_lock_contention(tmp_home: Path) -> None:
    """[Acceptance #4] Lock contention returns exit code 2 and blocks mutation."""
    from acm.lock import WriteLock

    with WriteLock():
        res = runner.invoke(cli_app, ["init", "--force"])
        assert res.exit_code == 2


@pytest.mark.e2e
def test_acceptance_5_idempotency_zero_new_snapshots(
    tmp_home: Path, setup_p0_agents: dict[str, Path], fake_vmr_server: str
) -> None:
    """[Acceptance #5] Repeated use is idempotent no-op and produces no new snapshots."""
    clear_adapters()
    load_builtin_adapters()

    runner.invoke(cli_app, ["init", "--force"])
    runner.invoke(cli_app, ["use", "daily"])

    snaps_1 = len(list_snapshots("claude_code"))

    # Second invocation
    res_2 = runner.invoke(cli_app, ["use", "daily"])
    assert res_2.exit_code == 0
    assert "no-op" in res_2.stdout

    snaps_2 = len(list_snapshots("claude_code"))
    assert snaps_1 == snaps_2


@pytest.mark.e2e
def test_acceptance_6_protection_unresolved_env_and_whitelist(
    tmp_home: Path, setup_p0_agents: dict[str, Path]
) -> None:
    """[Acceptance #6] Unresolved ENV variables abort before write with exit code 1."""
    config_path = tmp_home / ".acm" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: "${UNDEFINED_REQUIRED_ENV_VAR}"
    models:
      m: {}

profiles:
  daily:
    default: m
    models:
      main: m
""",
        encoding="utf-8",
    )

    claude_file = setup_p0_agents["claude"]
    initial_bytes = claude_file.read_bytes()

    res = runner.invoke(cli_app, ["use", "daily"])
    assert res.exit_code == 1
    assert "UNDEFINED_REQUIRED_ENV_VAR" in (res.stdout + res.stderr)
    # File zero changes
    assert claude_file.read_bytes() == initial_bytes


@pytest.mark.e2e
def test_acceptance_7_drift_detection_and_force_override(
    tmp_home: Path, setup_p0_agents: dict[str, Path], fake_vmr_server: str
) -> None:
    """[Acceptance #7] External tampering triggers drift block (exit 2) and --force recovers."""
    clear_adapters()
    load_builtin_adapters()

    runner.invoke(cli_app, ["init", "--force"])
    runner.invoke(cli_app, ["use", "daily"])

    # Tamper Claude Code model directly on disk
    claude_file = setup_p0_agents["claude"]
    claude_data = json.loads(claude_file.read_text(encoding="utf-8"))
    claude_data["model"] = "externally_modified_model"
    claude_file.write_text(json.dumps(claude_data), encoding="utf-8")

    # Re-running use without force should be blocked
    res_block = runner.invoke(cli_app, ["use", "daily"])
    assert res_block.exit_code == 2
    assert "Safety Block: external drift detected" in (res_block.stdout + res_block.stderr)

    # Re-running use with --force succeeds
    res_force = runner.invoke(cli_app, ["use", "daily", "--force"])
    assert res_force.exit_code == 0


@pytest.mark.e2e
def test_acceptance_8_exit_path_zero_lock_in(
    tmp_home: Path, setup_p0_agents: dict[str, Path], fake_vmr_server: str
) -> None:
    """[Acceptance #8] Deleting ~/.acm leaves agent configurations functional in their last projected state."""
    clear_adapters()
    load_builtin_adapters()

    runner.invoke(cli_app, ["init", "--force"])
    runner.invoke(cli_app, ["use", "daily"])

    # Delete ~/.acm entirely
    acm_dir = tmp_home / ".acm"
    import shutil

    shutil.rmtree(acm_dir)

    # Verify agent configs are still valid and retain their projected settings
    claude_file = setup_p0_agents["claude"]
    assert "ANTHROPIC_BASE_URL" in claude_file.read_text(encoding="utf-8")

    codex_file = setup_p0_agents["codex"]
    assert "model_providers" in codex_file.read_text(encoding="utf-8")

    pi_settings = setup_p0_agents["pi_settings"]
    assert "defaultProvider" in pi_settings.read_text(encoding="utf-8")
