# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for six-state machine and drift detection (WP4)."""

from pathlib import Path

from conftest import MockAdapter, make_mock_profile

from acm.state import LastWrite, save_last_write
from acm.status import AgentState, compute_agent_status, is_noop


def test_state_not_detected(tmp_home: Path) -> None:
    """Test NOT_DETECTED state when detect() is False."""
    target = tmp_home / "settings.json"
    adapter = MockAdapter(target, detected=False)
    profile = make_mock_profile()

    res = compute_agent_status(adapter, profile)
    assert res.state == AgentState.NOT_DETECTED


def test_state_unmanaged(tmp_home: Path) -> None:
    """Test UNMANAGED state when detected but last_write is None."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "existing"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)
    profile = make_mock_profile()

    res = compute_agent_status(adapter, profile)
    assert res.state == AgentState.UNMANAGED


def test_state_error_on_corrupted_json(tmp_home: Path) -> None:
    """Test ERROR state when target config file has broken syntax."""
    target = tmp_home / "settings.json"
    target.write_text("{corrupted json", encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    # Put a valid last_write so it does not stay UNMANAGED
    lw = LastWrite(
        profile="daily",
        timestamp="20260824000000",
        backup_id="20260824000000",
        fields={"model": "old-model"},
    )
    save_last_write(adapter.AGENT_ID, lw)

    res = compute_agent_status(adapter, make_mock_profile())
    assert res.state == AgentState.ERROR
    assert res.error_message is not None


def test_state_drifted(tmp_home: Path) -> None:
    """Test DRIFTED state when disk value deviates from last_write."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "tampered_by_user"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    lw = LastWrite(
        profile="daily",
        timestamp="20260824000000",
        backup_id="20260824000000",
        fields={"settings.json::model": "original_acm_model"},
    )
    save_last_write(adapter.AGENT_ID, lw)

    res = compute_agent_status(adapter, make_mock_profile("coding"))
    assert res.state == AgentState.DRIFTED
    assert len(res.drifts) == 1
    assert res.drifts[0].field == "model"
    assert res.drifts[0].expected == "original_acm_model"
    assert res.drifts[0].found == "tampered_by_user"


def test_state_out_of_sync(tmp_home: Path) -> None:
    """Test OUT_OF_SYNC state when disk matches last_write, but desired profile differs."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "coding"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    lw = LastWrite(
        profile="daily",
        timestamp="20260824000000",
        backup_id="20260824000000",
        fields={"settings.json::model": "coding"},
    )
    save_last_write(adapter.AGENT_ID, lw)

    # Desired profile requests "advanced" model
    desired_profile = make_mock_profile(model_id="advanced")
    res = compute_agent_status(adapter, desired_profile)
    assert res.state == AgentState.OUT_OF_SYNC


def test_state_synced(tmp_home: Path) -> None:
    """Test SYNCED state when disk matches both last_write and desired profile."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "coding"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    lw = LastWrite(
        profile="daily",
        timestamp="20260824000000",
        backup_id="20260824000000",
        fields={"settings.json::model": "coding"},
    )
    save_last_write(adapter.AGENT_ID, lw)

    desired_profile = make_mock_profile(model_id="coding")
    res = compute_agent_status(adapter, desired_profile)
    assert res.state == AgentState.SYNCED


def test_managed_paths_excludes_stale_field_no_longer_planned(tmp_home: Path) -> None:
    """§3.5: a stale last_write field the current plan() no longer produces (e.g.
    after switching to a no-default profile, or the user changed the model by
    hand) must not be compared for drift — only the intersection of last_write
    and the current plan's op paths is in scope."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "user_picked_this"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    lw = LastWrite(
        profile="daily",
        timestamp="20260824000000",
        backup_id="20260824000000",
        fields={"settings.json::model": "old_acm_model"},
    )
    save_last_write(adapter.AGENT_ID, lw)

    # Current profile has no default -> MockAdapter.plan() produces zero ops ->
    # managed_paths is empty -> the stale 'model' field is out of scope -> no DRIFTED.
    from acm.resolve import ResolvedProfile

    no_default_profile = ResolvedProfile(
        profile_name="daily", models=make_mock_profile("x").models, default_label=None
    )
    res = compute_agent_status(adapter, no_default_profile)
    assert res.state != AgentState.DRIFTED
    # Zero planned ops -> the (empty) ops-vs-disk comparison loop vacuously passes.
    assert res.state == AgentState.SYNCED


def test_drift_check_runs_with_no_resolved_profile(tmp_home: Path) -> None:
    """resolved_profile=None (e.g. no active profile) falls back to the pre-v2,
    unscoped drift comparison rather than crashing on a None dereference."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "tampered"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    lw = LastWrite(
        profile="daily",
        timestamp="20260824000000",
        backup_id="20260824000000",
        fields={"model": "original"},
    )
    save_last_write(adapter.AGENT_ID, lw)

    res = compute_agent_status(adapter, None)
    assert res.state == AgentState.DRIFTED


def test_is_noop_idempotency(tmp_home: Path) -> None:
    """Test is_noop helper returns True only when disk matches desired state."""
    target = tmp_home / "settings.json"
    target.write_text('{"model": "coding"}', encoding="utf-8")
    adapter = MockAdapter(target, detected=True)

    profile_same = make_mock_profile("coding")
    profile_diff = make_mock_profile("other")

    assert is_noop(adapter, profile_same) is True
    assert is_noop(adapter, profile_diff) is False
