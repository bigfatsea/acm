# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Six-state machine, drift detection, and idempotency evaluation for ACM."""

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

import tomlkit
from pydantic import BaseModel, ConfigDict, Field

from acm.adapters import ProjectionWarning
from acm.resolve import ResolvedProfile
from acm.safety import NOT_EXIST_SENTINEL, read_file_dotpath
from acm.state import load_last_write
from acm.util import get_env_map
from acm.writers.json_editor import NOT_FOUND


class AgentState(StrEnum):
    """Six configuration states representing host alignment with ACM."""

    SYNCED = "SYNCED"
    OUT_OF_SYNC = "OUT_OF_SYNC"
    DRIFTED = "DRIFTED"
    ERROR = "ERROR"
    UNMANAGED = "UNMANAGED"
    NOT_DETECTED = "NOT_DETECTED"


class DriftEntry(BaseModel):
    """Record of a drifted managed field."""

    model_config = ConfigDict(extra="forbid")

    field: str
    expected: Any
    found: Any


class AgentStatusResult(BaseModel):
    """Status assessment for a single agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    state: AgentState
    active_profile: str | None = None
    last_profile: str | None = None
    last_timestamp: str | None = None
    drifts: list[DriftEntry] = Field(default_factory=list)
    warnings: list[ProjectionWarning] = Field(default_factory=list)
    error_message: str | None = None


def detect_agent_drift(
    adapter: Any,
    env: Mapping[str, str] | None = None,
) -> list[DriftEntry]:
    """Detect external drift between disk reality and last_write record."""
    env_map = get_env_map(env)
    last_write = load_last_write(adapter.AGENT_ID, env_map)
    if not last_write:
        return []

    config_files = adapter.config_paths(env_map)
    drifts: list[DriftEntry] = []

    for raw_path, expected_val in last_write.fields.items():
        if "::" in raw_path:
            cf_name, dot_path = raw_path.split("::", 1)
            target_cfs = [cf for cf in config_files if cf.name == cf_name]
        else:
            cf_name, dot_path = None, raw_path
            target_cfs = config_files

        found_val: Any = NOT_FOUND
        for cf in target_cfs:
            val = read_file_dotpath(cf, dot_path)
            if val is not NOT_FOUND:
                found_val = val
                break

        # Check if file was created by ACM and subsequently deleted / archived
        if expected_val == NOT_EXIST_SENTINEL:
            if found_val is not NOT_FOUND:
                drifts.append(DriftEntry(field=dot_path, expected="<not_exist>", found=found_val))
        else:
            if found_val is NOT_FOUND:
                drifts.append(DriftEntry(field=dot_path, expected=expected_val, found="<missing>"))
            elif found_val != expected_val:
                drifts.append(DriftEntry(field=dot_path, expected=expected_val, found=found_val))

    return drifts


def is_noop(
    adapter: Any,
    resolved_profile: ResolvedProfile,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Check if applying resolved_profile would result in a zero-diff no-op."""
    env_map = get_env_map(env)
    ops, _ = adapter.plan(resolved_profile, env_map)
    if not ops:
        return True

    for op in ops:
        current_val = read_file_dotpath(op.file, op.path)
        if current_val != op.new:
            return False

    return True


def compute_agent_status(
    adapter: Any,
    resolved_profile: ResolvedProfile | None,
    env: Mapping[str, str] | None = None,
) -> AgentStatusResult:
    """Assess and return the configuration state of an agent against ACM.

    Priority hierarchy:
    ERROR > DRIFTED > OUT_OF_SYNC > SYNCED.
    NOT_DETECTED and UNMANAGED are evaluated prior to file comparison.
    """
    env_map = get_env_map(env)
    agent_id = adapter.AGENT_ID
    display_name = adapter.DISPLAY_NAME

    # 1. Detection
    if not adapter.detect(env_map):
        return AgentStatusResult(
            agent_id=agent_id,
            display_name=display_name,
            state=AgentState.NOT_DETECTED,
        )

    # 2. File readability / syntax error check
    config_files = adapter.config_paths(env_map)
    for cf in config_files:
        if cf.exists():
            try:
                content = cf.read_text(encoding="utf-8")
                if cf.suffix == ".json":
                    json.loads(content)
                elif cf.suffix == ".toml":
                    tomlkit.parse(content)
            except (
                json.JSONDecodeError,
                tomlkit.exceptions.TOMLKitError,
                UnicodeDecodeError,
                OSError,
            ) as e:
                return AgentStatusResult(
                    agent_id=agent_id,
                    display_name=display_name,
                    state=AgentState.ERROR,
                    error_message=f"Syntax error reading {cf.name}: {e}",
                )

    # 3. Last write inspection
    last_write = load_last_write(agent_id, env_map)
    if last_write is None:
        return AgentStatusResult(
            agent_id=agent_id,
            display_name=display_name,
            state=AgentState.UNMANAGED,
        )

    # 4. Drift check
    drifts = detect_agent_drift(adapter, env_map)
    if drifts:
        return AgentStatusResult(
            agent_id=agent_id,
            display_name=display_name,
            state=AgentState.DRIFTED,
            active_profile=resolved_profile.profile_name if resolved_profile else None,
            last_profile=last_write.profile,
            last_timestamp=last_write.timestamp,
            drifts=drifts,
        )

    # 5. Desired profile comparison
    if resolved_profile is None:
        return AgentStatusResult(
            agent_id=agent_id,
            display_name=display_name,
            state=AgentState.UNMANAGED,
            last_profile=last_write.profile,
            last_timestamp=last_write.timestamp,
        )

    # Compile desired state
    ops, warnings = adapter.plan(resolved_profile, env_map)
    for op in ops:
        disk_val = read_file_dotpath(op.file, op.path)
        if disk_val != op.new:
            return AgentStatusResult(
                agent_id=agent_id,
                display_name=display_name,
                state=AgentState.OUT_OF_SYNC,
                active_profile=resolved_profile.profile_name,
                last_profile=last_write.profile,
                last_timestamp=last_write.timestamp,
                warnings=warnings,
            )

    return AgentStatusResult(
        agent_id=agent_id,
        display_name=display_name,
        state=AgentState.SYNCED,
        active_profile=resolved_profile.profile_name,
        last_profile=last_write.profile,
        last_timestamp=last_write.timestamp,
        warnings=warnings,
    )
