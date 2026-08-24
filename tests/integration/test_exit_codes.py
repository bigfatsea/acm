# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Subprocess integration tests validating the CLI exit code matrix."""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from acm.lock import WriteLock


def run_acm_subprocess(args: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    """Execute python -m acm as a real isolated subprocess."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent / "src")
    return subprocess.run(
        [sys.executable, "-m", "acm", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_subprocess_usage_error_exits_1(tmp_home: Path) -> None:
    """Test unrecognized subcommand exits with 1 (not 2)."""
    res = run_acm_subprocess(["non_existent_command"], tmp_home)
    assert res.returncode == 1


def test_subprocess_unknown_profile_exits_4(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_toml: str
) -> None:
    """Test unknown profile name exits with 4."""
    make_config(sample_config_toml)
    res = run_acm_subprocess(["use", "non_existent_profile"], tmp_home)
    assert res.returncode == 4


def test_subprocess_drift_safety_block_exits_2(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_toml: str
) -> None:
    """Test external drift safety block exits with 2."""
    make_config(sample_config_toml)
    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_file = claude_dir / "settings.json"
    claude_file.write_text('{"model": "old"}', encoding="utf-8")

    # Initial use
    res_use1 = run_acm_subprocess(["use", "daily"], tmp_home)
    assert res_use1.returncode == 0

    # Tamper externally
    claude_file.write_text('{"model": "tampered"}', encoding="utf-8")

    # Drifted use without --force
    res_use2 = run_acm_subprocess(["use", "direct"], tmp_home)
    assert res_use2.returncode == 2
    assert "Safety Block: external drift detected" in (res_use2.stdout + res_use2.stderr)


def test_subprocess_lock_contention_exits_2(
    tmp_home: Path, make_config: Callable[[str], Path], sample_config_toml: str
) -> None:
    """Test lock contention safety block exits with 2."""
    make_config(sample_config_toml)
    env = {"HOME": str(tmp_home)}
    with WriteLock(env=env):
        res = run_acm_subprocess(["init", "--force"], tmp_home)
        assert res.returncode == 2
        assert "holding the write lock" in (res.stdout + res.stderr)
