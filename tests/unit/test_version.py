# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Test basic package metadata and version."""

from acm import __version__


def test_version() -> None:
    """Verify package version is set."""
    assert __version__ == "0.3.0"
