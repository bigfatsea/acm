"""Adapter registry (explicit list)."""

from typing import Any


def find_adapter(name: str) -> Any | None:
    """Return the adapter for an agent id/alias, or None (filled in with the adapters)."""
    return None
