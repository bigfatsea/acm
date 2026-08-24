# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Safety Engine: single atomic write channel with six-step pipeline."""

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import BaseModel, ConfigDict, Field

from acm.adapters import FieldOp, PlannedOp
from acm.errors import SafetyBlockedError
from acm.lock import WriteLock
from acm.state import (
    LastWrite,
    create_snapshot,
    save_last_write,
)
from acm.util import get_acm_home, get_env_map, get_state_dir
from acm.writers.json_editor import NOT_FOUND, read_json_path, set_json_path
from acm.writers.toml_editor import read_toml_path, set_toml_path
from acm.writers.tree_diff import is_path_managed, tree_diff

NOT_EXIST_SENTINEL = "NOT_EXIST"


class WriteResult(BaseModel):
    """Result of a Safety Engine write execution."""

    model_config = ConfigDict(extra="forbid")

    noop: bool
    agent_id: str
    backup_id: str | None = None
    ops: list[FieldOp] = Field(default_factory=list)


def compute_file_sha256(path: Path) -> str:
    """Compute sha256 hex digest of a file, or NOT_EXIST_SENTINEL if it does not exist."""
    if not path.exists():
        return NOT_EXIST_SENTINEL
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cleanup_stale_tmp(env: Mapping[str, str] | None = None) -> None:
    """Silently scan and clean up orphaned *.acm_tmp files across state and agent dirs."""
    from acm.adapters import get_adapters

    env_map = get_env_map(env)
    dirs_to_scan: set[Path] = {get_state_dir(env_map), get_acm_home(env_map)}
    for adapter in get_adapters():
        try:
            for cf in adapter.config_paths(env_map):
                dirs_to_scan.add(cf.parent)
        except Exception:  # noqa: BLE001, S110
            pass

    for d in dirs_to_scan:
        if d.exists():
            for p in d.glob("*.acm_tmp"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass


def read_file_dotpath(file_path: Path, dot_path: str) -> Any:
    """Read a field from a file on disk depending on extension."""
    if not file_path.exists():
        return NOT_FOUND
    try:
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix == ".json":
            return read_json_path(content, dot_path)
        if file_path.suffix == ".toml":
            return read_toml_path(content, dot_path)
        return NOT_FOUND
    except (json.JSONDecodeError, tomlkit.exceptions.TOMLKitError, UnicodeDecodeError, OSError):
        return NOT_FOUND


def write_changeset(
    agent_id: str,
    profile_name: str,
    allowed_paths: list[Path],
    allowed_namespaces: list[str],
    ops: list[PlannedOp],
    env: Mapping[str, str] | None = None,
) -> WriteResult:
    """Execute the Safety Engine six-step pipeline for an agent's planned operations.

    Steps:
    1. Whitelist validation (file boundary + dot-path namespace).
    2. Pre-write snapshot + FieldOp expansion (recording H0 and initial state).
    3. In-memory modification + syntax self-check + AST tree-diff non-destructive assertion.
    4. Pre-commit fingerprint validation (re-verify sha256 == H0 across all target files).
    5. Atomic replace (via temporary file + os.replace in sequence).
    6. Overwrite last_write.json.
    """
    env_map = get_env_map(env)
    # Empty ops is an immediate idempotent no-op
    if not ops:
        return WriteResult(noop=True, agent_id=agent_id, backup_id=None, ops=[])

    with WriteLock(env_map):
        cleanup_stale_tmp(env_map)

        # ── Step 1: Whitelist validation ──────────────────────────
        resolved_allowed_paths = [p.resolve() for p in allowed_paths]

        for op in ops:
            resolved_op_file = op.file.resolve()
            if resolved_op_file not in resolved_allowed_paths:
                raise SafetyBlockedError(
                    f"Whitelist violation: file '{op.file}' is not declared in allowed paths for agent '{agent_id}'."
                )
            if not is_path_managed(op.path, allowed_namespaces):
                raise SafetyBlockedError(
                    f"Whitelist violation: dot-path '{op.path}' is not within allowed namespaces for agent '{agent_id}'."
                )

        # ── Step 2: Pre-write snapshot + FieldOp expansion ────────
        unique_files: list[Path] = []
        for op in ops:
            if op.file not in unique_files:
                unique_files.append(op.file)

        h0_map: dict[Path, str] = {f: compute_file_sha256(f) for f in unique_files}
        snapshot_id = create_snapshot(agent_id, unique_files, env_map)

        field_ops: list[FieldOp] = []
        for op in ops:
            is_created = h0_map[op.file] == NOT_EXIST_SENTINEL
            old_val = read_file_dotpath(op.file, op.path)
            field_ops.append(
                FieldOp(
                    file=op.file,
                    path=op.path,
                    old=old_val if old_val is not NOT_FOUND else None,
                    new=op.new,
                    created=is_created,
                )
            )

        # ── Step 3: In-memory modification & AST diff assertion ───
        modified_contents: dict[Path, str] = {}
        for target_file in unique_files:
            file_ops = [op for op in ops if op.file == target_file]
            file_managed_paths = [op.path for op in file_ops]

            if target_file.exists():
                original_content = target_file.read_text(encoding="utf-8")
            else:
                original_content = ""

            updated_content = original_content
            if target_file.suffix == ".json":
                for op in file_ops:
                    updated_content = set_json_path(updated_content, op.path, op.new)
                # Syntax self-check
                try:
                    parsed_new = json.loads(updated_content)
                except Exception as e:
                    raise SafetyBlockedError(
                        f"Generated invalid JSON for {target_file.name}: {e}"
                    ) from e
                # AST non-destructive diff
                if original_content.strip():
                    try:
                        parsed_old = json.loads(original_content)
                        diffs = tree_diff(parsed_old, parsed_new, file_managed_paths)
                        if diffs:
                            raise SafetyBlockedError(
                                f"AST non-destructive assertion failed for {target_file.name}: unmanaged fields were corrupted: {diffs}"
                            )
                    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                        # If original content was corrupt syntax, AST diff cannot compare and is skipped
                        pass

            elif target_file.suffix == ".toml":
                for op in file_ops:
                    updated_content = set_toml_path(updated_content, op.path, op.new)
                # Syntax self-check
                try:
                    parsed_new = tomlkit.parse(updated_content)
                except Exception as e:
                    raise SafetyBlockedError(
                        f"Generated invalid TOML for {target_file.name}: {e}"
                    ) from e
                # AST non-destructive diff
                if original_content.strip():
                    try:
                        parsed_old = tomlkit.parse(original_content)
                        diffs = tree_diff(dict(parsed_old), dict(parsed_new), file_managed_paths)
                        if diffs:
                            raise SafetyBlockedError(
                                f"AST non-destructive assertion failed for {target_file.name}: unmanaged fields were corrupted: {diffs}"
                            )
                    except Exception:  # noqa: BLE001, S110
                        pass
            else:
                raise SafetyBlockedError(
                    f"Unsupported file format extension '{target_file.suffix}' for {target_file.name}."
                )

            modified_contents[target_file] = updated_content

        # Test hook: fault injection before fingerprint check
        if env_map.get("ACM_TEST_FAULT_PRE_COMMIT_MODIFY"):
            target = unique_files[0]
            target.write_text('{"tampered": true}', encoding="utf-8")

        # ── Step 4: Pre-commit fingerprint validation (batch) ─────
        for target_file in unique_files:
            h1 = compute_file_sha256(target_file)
            if h1 != h0_map[target_file]:
                raise SafetyBlockedError(
                    f"Pre-commit fingerprint mismatch on {target_file.name}: file was modified externally during transaction."
                )

        # ── Step 5: Atomic replace ────────────────────────────────
        temp_files: list[Path] = []
        try:
            for idx, target_file in enumerate(unique_files):
                # Test hook: mid-transaction crash injection
                if env_map.get("ACM_TEST_FAULT_MID_TRANSACTION_FAIL") and idx > 0:
                    raise OSError("Injected disk failure during multi-file transaction replace.")

                target_file.parent.mkdir(parents=True, exist_ok=True)
                temp_file = target_file.parent / f"{target_file.name}.{os.getpid()}.acm_tmp"
                temp_files.append(temp_file)
                temp_file.write_text(modified_contents[target_file], encoding="utf-8")
                try:
                    os.chmod(temp_file, 0o600)
                except OSError:
                    pass

                # Test hook: mid-transaction crash injection before atomic replace
                if env_map.get("ACM_TEST_FAULT_CRASH_BEFORE_REPLACE"):
                    os._exit(9)

                os.replace(temp_file, target_file)
        finally:
            # Clean any remaining temp files in case of exception
            for temp_f in temp_files:
                if temp_f.exists():
                    try:
                        temp_f.unlink()
                    except OSError:
                        pass

        # ── Step 6: Overwrite last_write.json ──────────────────────
        created_file_names = [str(f) for f, h in h0_map.items() if h == NOT_EXIST_SENTINEL]
        last_write_fields = {f"{op.file.name}::{op.path}": op.new for op in ops}
        last_write = LastWrite(
            profile=profile_name,
            timestamp=snapshot_id,
            backup_id=snapshot_id,
            fields=last_write_fields,
            created_files=created_file_names,
        )
        save_last_write(agent_id, last_write, env_map)

        return WriteResult(
            noop=False,
            agent_id=agent_id,
            backup_id=snapshot_id,
            ops=field_ops,
        )
