import os
from collections.abc import Iterator

import pytest

# The autouse isolation fixture in tests/conftest.py strips PATH; capture the real one first.
_REAL_PATH = os.environ.get("PATH", "")


@pytest.fixture(autouse=True)
def _real_path(monkeypatch: pytest.MonkeyPatch, isolated_env: dict[str, str]) -> Iterator[None]:
    monkeypatch.setenv("REAL_PATH", _REAL_PATH)
    yield
