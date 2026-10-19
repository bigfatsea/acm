import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import team_manifest

from acm.cli.main import main


@pytest.fixture
def stub_agents(tmp_path: Path) -> Callable[..., Path]:
    """Install stub executables for agents into the isolated PATH directory."""
    bindir = Path(os.environ["PATH"].split(os.pathsep)[0])

    def install(*names: str) -> Path:
        for n in names:
            p = bindir / n
            p.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$0 $*" > "$ACM_STUB_OUT"\nenv >> "$ACM_STUB_OUT"\n'
            )
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return bindir

    return install


@pytest.fixture
def team(gateway, monkeypatch):
    """A running fake gateway publishing the team manifest; VMR_KEY already exported."""
    gateway.manifest = team_manifest(gateway.url)
    monkeypatch.setenv("VMR_KEY", gateway.key)
    return gateway


@pytest.fixture
def acm(capsys):
    """Run the CLI in-process: acm("use", "daily") -> (exit code, stdout, stderr)."""

    def call(*args: str) -> tuple[int, str, str]:
        code = main(["acm", *args])
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    return call


@pytest.fixture
def claude_home(home: Path) -> Path:
    d = home / ".claude"
    d.mkdir()
    (d / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(git status)"]}, "env": {"X": "1"}}, indent=2)
        + "\n"
    )
    return d / "settings.json"
