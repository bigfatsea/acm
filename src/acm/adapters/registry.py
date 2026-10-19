"""Adapter registry (explicit list: no reflection, no dynamic loading)."""

from acm.adapters.base import Adapter
from acm.adapters.claude_code import ClaudeCode
from acm.adapters.codex import Codex
from acm.adapters.hermes import Hermes
from acm.adapters.openclaw import OpenClaw
from acm.adapters.opencode import DEVECO, MIMO, OPENCODE, OpenCodeFamily
from acm.adapters.pi import OMO, PI, PRIME, PiFamily


def all_adapters() -> list[Adapter]:
    return list(_ADAPTERS)


def find_adapter(name: str) -> Adapter | None:
    for a in _ADAPTERS:
        if a.matches(name):
            return a
    return None


_ADAPTERS: list[Adapter] = [
    ClaudeCode(),
    Codex(),
    PiFamily(PI),
    PiFamily(OMO),
    PiFamily(PRIME),
    OpenCodeFamily(OPENCODE),
    OpenCodeFamily(MIMO),
    OpenCodeFamily(DEVECO),
    Hermes(),
    OpenClaw(),
]
