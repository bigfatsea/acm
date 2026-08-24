# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Crash resilience, SIGKILL simulation, and stale temp file cleanup tests (WP3, Code Review Round 2/3)."""

import multiprocessing
from pathlib import Path

from acm.adapters import PlannedOp, clear_adapters, load_builtin_adapters
from acm.safety import cleanup_stale_tmp, write_changeset
from acm.util import get_state_dir


def _real_write_changeset_crash_worker(home_path: str) -> None:
    """Worker function that runs write_changeset and crashes mid-transaction right before atomic replace."""
    c_dir = Path(home_path) / ".claude"
    target_file = c_dir / "settings.json"
    env_map = {
        "HOME": home_path,
        "ACM_TEST_FAULT_CRASH_BEFORE_REPLACE": "1",
    }
    ops = [PlannedOp(file=target_file, path="model", new="crashed-new-model")]
    allowed_paths = [target_file]
    allowed_namespaces = ["model"]
    write_changeset("claude_code", "daily", allowed_paths, allowed_namespaces, ops, env=env_map)


def test_cleanup_stale_tmp_files(tmp_home: Path) -> None:
    """Test that startup cleanup silently removes leftover *.acm_tmp files across state and agent directories."""
    clear_adapters()
    load_builtin_adapters()

    state_dir = get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)

    # 1. State dir orphans
    orphan_temp1 = state_dir / "file1.12345.acm_tmp"
    orphan_temp1.write_text("corrupted", encoding="utf-8")

    # 2. Agent dir orphans (e.g. ~/.claude and ~/.codex)
    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    orphan_claude = claude_dir / "settings.json.9999.acm_tmp"
    orphan_claude.write_text("corrupted", encoding="utf-8")

    codex_dir = tmp_home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    orphan_codex = codex_dir / "config.toml.8888.acm_tmp"
    orphan_codex.write_text("corrupted", encoding="utf-8")

    assert orphan_temp1.exists()
    assert orphan_claude.exists()
    assert orphan_codex.exists()

    cleanup_stale_tmp()

    assert not orphan_temp1.exists()
    assert not orphan_claude.exists()
    assert not orphan_codex.exists()


def test_real_write_changeset_sigkill_crash_resilience(tmp_home: Path) -> None:
    """[Acceptance #4 Real Pipeline Test] Test that a SIGKILL / hard crash during write_changeset leaves target file intact and temp is cleaned up."""
    clear_adapters()
    load_builtin_adapters()

    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    target_file = claude_dir / "settings.json"
    initial_content = '{\n  "model": "original-stable",\n  "custom": 123\n}\n'
    target_file.write_text(initial_content, encoding="utf-8")

    p = multiprocessing.Process(target=_real_write_changeset_crash_worker, args=(str(tmp_home),))
    p.start()
    p.join()
    assert p.exitcode in (-9, 9)

    # 1. Target file was NOT replaced or corrupted by the crash
    assert target_file.read_text(encoding="utf-8") == initial_content

    # 2. Leftover .acm_tmp file exists in ~/.claude/
    leftover_tmps = list(claude_dir.glob("*.acm_tmp"))
    assert len(leftover_tmps) == 1

    # 3. Running startup cleanup removes the leftover temp file
    cleanup_stale_tmp(env={"HOME": str(tmp_home)})
    assert len(list(claude_dir.glob("*.acm_tmp"))) == 0
