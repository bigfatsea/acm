# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for projection engine (WP4)."""

from pathlib import Path

from conftest import MockAdapter, make_mock_profile

from acm.projection import compute_desired_state


def test_compute_desired_state(tmp_home: Path) -> None:
    """Test compute_desired_state compiles operations across adapters."""
    file1 = tmp_home / "agent1.json"
    file2 = tmp_home / "agent2.json"
    adapter1 = MockAdapter(file1)
    adapter1.AGENT_ID = "agent_1"
    adapter2 = MockAdapter(file2)
    adapter2.AGENT_ID = "agent_2"

    profile = make_mock_profile(model_id="claude-3-7-sonnet")
    desired = compute_desired_state(profile, [adapter1, adapter2])

    assert "agent_1" in desired
    assert "agent_2" in desired
    assert desired["agent_1"][0][0].new == "claude-3-7-sonnet"
    assert desired["agent_2"][0][0].new == "claude-3-7-sonnet"
