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


# ── Shared adapter helpers (schema v2): _effective_default / _unreachable_members /
# check_unsupported_profile_specs (collapsed to a single-member check) ──────────


def _profile_two_members(default_label: str | None):
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    prov_a = ResolvedProvider(
        name="a", protocol="openai", base_url="http://a", api_key="k", raw_api_key_ref="k"
    )
    prov_b = ResolvedProvider(
        name="b", protocol="openai", base_url="http://b", api_key="k", raw_api_key_ref="k"
    )
    return ResolvedProfile(
        profile_name="p",
        models={
            "main": ResolvedModel(model_id="coding", provider=prov_a),
            "other": ResolvedModel(model_id="o3", provider=prov_b),
        },
        default_label=default_label,
    )


def test_effective_default_present() -> None:
    from acm.adapters import _effective_default

    profile = _profile_two_members(default_label="main")
    result = _effective_default(profile)
    assert result is not None
    label, model = result
    assert label == "main"
    assert model.model_id == "coding"


def test_effective_default_absent() -> None:
    from acm.adapters import _effective_default

    profile = _profile_two_members(default_label=None)
    assert _effective_default(profile) is None


def test_unreachable_members_excludes_default() -> None:
    from acm.adapters import _unreachable_members

    profile = _profile_two_members(default_label="main")
    unreachable = _unreachable_members(profile, "main")
    assert [label for label, _ in unreachable] == ["other"]


def test_unreachable_members_distinguishes_same_id_different_provider() -> None:
    """A member on a different provider sharing the default's upstream id string is
    still unreachable — comparison is by (provider, model_id), not bare id."""
    from acm.adapters import _unreachable_members
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    prov_a = ResolvedProvider(
        name="a", protocol="openai", base_url="http://a", api_key="k", raw_api_key_ref="k"
    )
    prov_b = ResolvedProvider(
        name="b", protocol="openai", base_url="http://b", api_key="k", raw_api_key_ref="k"
    )
    profile = ResolvedProfile(
        profile_name="p",
        models={
            "main": ResolvedModel(model_id="same-id", provider=prov_a),
            "other": ResolvedModel(model_id="same-id", provider=prov_b),
        },
        default_label="main",
    )
    unreachable = _unreachable_members(profile, "main")
    assert [label for label, _ in unreachable] == ["other"]


def test_check_unsupported_profile_specs_none_member() -> None:
    from acm.adapters import check_unsupported_profile_specs

    assert check_unsupported_profile_specs(None, "agent", set()) == []


def test_check_unsupported_profile_specs_flags_unsupported_fields() -> None:
    from acm.adapters import check_unsupported_profile_specs
    from acm.config import ModelCapabilities
    from acm.resolve import ResolvedModel, ResolvedProvider

    prov = ResolvedProvider(
        name="a",
        protocol="openai",
        base_url="http://a",
        api_key="k",
        raw_api_key_ref="k",
        headers={"X-Custom": "v"},
        proxy="http://proxy",
    )
    model = ResolvedModel(
        model_id="coding",
        provider=prov,
        temperature=0.5,
        capabilities=ModelCapabilities(vision=True),
    )
    warnings = check_unsupported_profile_specs(model, "agent", supported_fields=set())
    fields = {w.field for w in warnings}
    assert fields == {"temperature", "capabilities", "provider.headers", "provider.proxy"}


def test_check_unsupported_profile_specs_respects_supported_fields() -> None:
    from acm.adapters import check_unsupported_profile_specs
    from acm.resolve import ResolvedModel, ResolvedProvider

    prov = ResolvedProvider(
        name="a", protocol="openai", base_url="http://a", api_key="k", raw_api_key_ref="k"
    )
    model = ResolvedModel(model_id="coding", provider=prov, temperature=0.5)
    warnings = check_unsupported_profile_specs(
        model, "agent", supported_fields={"temperature"}
    )
    assert warnings == []
