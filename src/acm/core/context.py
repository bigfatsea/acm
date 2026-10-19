"""Execution context threaded through commands, engine and adapters."""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Ctx:
    """Environment and global flags for one ACM invocation.

    ``env`` is explicit so tests (and ``acm run``) never depend on ``os.environ``
    implicitly; ``home`` is where agents keep their per-user config.
    """

    env: Mapping[str, str] = field(repr=False)  # may hold secrets: never print it
    home: Path
    acm_home: Path
    dry_run: bool = False
    force: bool = False
    yes: bool = False
    verbose: bool = False
    show_secrets: bool = False
    interactive: bool = False

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        interactive: bool | None = None,
        dry_run: bool = False,
        force: bool = False,
        yes: bool = False,
        verbose: bool = False,
        show_secrets: bool = False,
    ) -> "Ctx":
        env_map: Mapping[str, str] = os.environ if env is None else env
        home = Path(env_map["HOME"]) if env_map.get("HOME") else Path.home()
        acm_home = Path(env_map["ACM_HOME"]) if env_map.get("ACM_HOME") else home / ".acm"
        if interactive is None:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        return cls(
            env=env_map,
            home=home,
            acm_home=acm_home,
            interactive=interactive,
            dry_run=dry_run,
            force=force,
            yes=yes,
            verbose=verbose,
            show_secrets=show_secrets,
        )

    def with_flags(self, **flags: Any) -> "Ctx":
        return replace(self, **flags)

    @property
    def config_path(self) -> Path:
        return self.acm_home / "config.yaml"

    @property
    def state_dir(self) -> Path:
        return self.acm_home / "state"

    @property
    def lock_path(self) -> Path:
        return self.state_dir / ".lock"

    @property
    def objects_dir(self) -> Path:
        return self.state_dir / "objects"

    @property
    def history_path(self) -> Path:
        return self.state_dir / "history.jsonl"

    @property
    def manifests_dir(self) -> Path:
        return self.state_dir / "manifests"

    @property
    def run_dir(self) -> Path:
        return self.state_dir / "run"

    def expand(self, path: str) -> Path:
        """Expand ``~`` against this context's home (not the process's)."""
        if path == "~" or path.startswith("~/"):
            return self.home / path[2:] if path != "~" else self.home
        return Path(path)
