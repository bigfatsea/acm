# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""State directory management, last_write tracking, and snapshot storage."""

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from acm.util import get_logs_dir, get_state_dir


class LastWrite(BaseModel):
    """Record of the most recent successful projection for an agent."""

    model_config = ConfigDict(extra="forbid")

    profile: str
    timestamp: str
    backup_id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    created_files: list[str] = Field(default_factory=list)


def ensure_state_dirs(env: Mapping[str, str] | None = None) -> None:
    """Ensure state and logs directories exist with 0700 permissions."""
    state_dir = get_state_dir(env)
    logs_dir = get_logs_dir(env)

    for directory in (state_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass


def get_active_path(env: Mapping[str, str] | None = None) -> Path:
    """Return path to ~/.acm/state/active."""
    return get_state_dir(env) / "active"


def read_active(env: Mapping[str, str] | None = None) -> str | None:
    """Read the currently active profile name, or None if not set."""
    p = get_active_path(env)
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8").strip()
        return content if content else None
    except OSError:
        return None


def write_active(profile: str, env: Mapping[str, str] | None = None) -> None:
    """Write the active profile name to ~/.acm/state/active."""
    ensure_state_dirs(env)
    p = get_active_path(env)
    temp_path = p.parent / f"active.{os.getpid()}.acm_tmp"
    temp_path.write_text(profile.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(temp_path, 0o600)
    except OSError:
        pass
    os.replace(temp_path, p)


def get_last_write_path(agent_id: str, env: Mapping[str, str] | None = None) -> Path:
    """Return path to ~/.acm/state/<agent_id>/last_write.json."""
    return get_state_dir(env) / agent_id / "last_write.json"


def load_last_write(agent_id: str, env: Mapping[str, str] | None = None) -> LastWrite | None:
    """Load the last_write record for an agent, or None if never written."""
    p = get_last_write_path(agent_id, env)
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        return LastWrite.model_validate(data)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def save_last_write(
    agent_id: str, last_write: LastWrite, env: Mapping[str, str] | None = None
) -> None:
    """Persist last_write record for an agent with 0600 permissions."""
    ensure_state_dirs(env)
    agent_dir = get_state_dir(env) / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(agent_dir, 0o700)
    except OSError:
        pass

    target = get_last_write_path(agent_id, env)
    temp_path = target.parent / f"last_write.{os.getpid()}.acm_tmp"
    content = json.dumps(last_write.model_dump(), indent=2) + "\n"
    temp_path.write_text(content, encoding="utf-8")
    try:
        os.chmod(temp_path, 0o600)
    except OSError:
        pass
    os.replace(temp_path, target)


def get_snapshots_dir(agent_id: str, env: Mapping[str, str] | None = None) -> Path:
    """Return root snapshots directory for an agent (~/.acm/state/<agent_id>/snapshots)."""
    return get_state_dir(env) / agent_id / "snapshots"


def generate_snapshot_id() -> str:
    """Generate a UTC lexicographically sortable timestamp snapshot ID."""
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


def create_snapshot(agent_id: str, files: list[Path], env: Mapping[str, str] | None = None) -> str:
    """Create an append-only snapshot directory for target files before mutation.

    Returns the generated snapshot_id (timestamp).
    """
    ensure_state_dirs(env)
    snapshot_id = generate_snapshot_id()
    snapshots_root = get_snapshots_dir(agent_id, env)
    counter = 1
    orig_id = snapshot_id
    while (snapshots_root / snapshot_id).exists():
        snapshot_id = f"{orig_id}_{counter:03d}"
        counter += 1

    snap_dir = snapshots_root / snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(snap_dir, 0o700)
    except OSError:
        pass

    for file_path in files:
        if file_path.exists():
            dest = snap_dir / file_path.name
            raw_bytes = file_path.read_bytes()
            dest.write_bytes(raw_bytes)
            try:
                os.chmod(dest, 0o600)
            except OSError:
                pass
        else:
            # Record sentinel marker for pre-write non-existence
            sentinel = snap_dir / f".not_exist_{file_path.name}"
            sentinel.write_text("NOT_EXIST\n", encoding="utf-8")
            try:
                os.chmod(sentinel, 0o600)
            except OSError:
                pass

    return snapshot_id


def list_snapshots(agent_id: str, env: Mapping[str, str] | None = None) -> list[str]:
    """List all snapshot IDs for an agent in ascending chronological order."""
    snap_root = get_snapshots_dir(agent_id, env)
    if not snap_root.exists():
        return []
    items = [p.name for p in snap_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    return sorted(items)
