"""Adapter registry (explicit list: no reflection, no dynamic loading)."""

from acm.adapters.base import Adapter
from acm.adapters.claude_code import ClaudeCode


def all_adapters() -> list[Adapter]:
    return list(_ADAPTERS)


def find_adapter(name: str) -> Adapter | None:
    for a in _ADAPTERS:
        if a.matches(name):
            return a
    return None


_ADAPTERS: list[Adapter] = [ClaudeCode()]
