# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Lock contention tests for WriteLock (WP3)."""

from pathlib import Path

import pytest

from acm.errors import SafetyBlockedError
from acm.lock import WriteLock


def test_lock_contention_blocks_second_process(tmp_home: Path) -> None:
    """Test that two simultaneous lock acquisitions result in SafetyBlockedError."""
    with (
        WriteLock(),
        pytest.raises(SafetyBlockedError, match="Another acm process is holding the write lock"),
        WriteLock(),
    ):
        pass


def test_lock_released_allows_reacquisition(tmp_home: Path) -> None:
    """Test that releasing lock allows subsequent acquisition."""
    with WriteLock():
        pass  # Released on exit

    with WriteLock():
        pass  # Reacquired successfully
