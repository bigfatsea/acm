"""Shared fixtures. Every test runs in an isolated HOME with no network and a stripped PATH."""

import os
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from acm.core.context import Ctx

_ACM_VARS = (
    "ACM_HOME",
    "ACM_MANIFEST",
    "ACM_MANIFEST_TIMEOUT",
    "ACM_VMR_PROBE_URL",
    "VMR_URL",
    "VMR_KEY",
)
_DEAD = "http://127.0.0.1:9"


# Only these survive from the real environment; everything else (API keys, proxies, tool
# config...) is removed so tests can neither depend on nor leak it.
_KEEP = {"LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "LOGNAME"}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Fake HOME, minimal PATH, scrubbed environment, gateway probes pinned to a dead port."""
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for var in list(os.environ):
        if var not in _KEEP:
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("ACM_VMR_PROBE_URL", _DEAD)
    monkeypatch.setenv("ACM_MANIFEST_TIMEOUT", "0.5")
    yield dict(os.environ)


@pytest.fixture
def home(isolated_env: dict[str, str]) -> Path:
    return Path(isolated_env["HOME"])


@pytest.fixture
def ctx(isolated_env: dict[str, str]) -> Ctx:
    return Ctx.from_env(dict(isolated_env), interactive=False)


@pytest.fixture
def make_config(ctx: Ctx) -> Callable[[str], Path]:
    """Write a dedented config.yaml into the isolated ACM home."""

    def _make(text: str) -> Path:
        ctx.acm_home.mkdir(parents=True, exist_ok=True)
        ctx.config_path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
        return ctx.config_path

    return _make
