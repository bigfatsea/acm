# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Path and environment utilities for ACM."""

import os
from collections.abc import Mapping
from pathlib import Path


def get_env_map(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    """Return active environment mapping, defaulting to os.environ."""
    return os.environ if env is None else env


def get_home(env: Mapping[str, str] | None = None) -> Path:
    """Resolve user HOME directory from env or system."""
    env_map = get_env_map(env)
    home_str = env_map.get("HOME")
    if home_str:
        return Path(home_str)
    return Path.home()


def get_acm_home(env: Mapping[str, str] | None = None) -> Path:
    """Resolve ACM configuration root directory (~/.acm by default)."""
    env_map = get_env_map(env)
    acm_home = env_map.get("ACM_HOME")
    if acm_home:
        return Path(acm_home)
    return get_home(env_map) / ".acm"


CONFIG_FILENAME = "config.yaml"


def get_config_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the absolute path of ACM's Core Config file (~/.acm/config.yaml)."""
    return get_acm_home(env) / CONFIG_FILENAME


def get_state_dir(env: Mapping[str, str] | None = None) -> Path:
    """Resolve ACM state directory (~/.acm/state)."""
    return get_acm_home(env) / "state"


def get_logs_dir(env: Mapping[str, str] | None = None) -> Path:
    """Resolve ACM logs directory (~/.acm/logs)."""
    return get_acm_home(env) / "logs"


def get_lock_file(env: Mapping[str, str] | None = None) -> Path:
    """Resolve ACM global lock file (~/.acm/state/.lock)."""
    return get_state_dir(env) / ".lock"


def resolve_agent_path(agent_id: str, rel: str, env: Mapping[str, str] | None = None) -> Path:
    """Resolve path to an agent's configuration file relative to user home."""
    env_map = get_env_map(env)
    return get_home(env_map) / rel
