# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Golden tests for registration-only profiles (no `default`, schema v3)."""

import json
from pathlib import Path

from acm.adapters import claude_code, codex, pi
from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider
from acm.safety import write_changeset


def make_registration_only_profile() -> ResolvedProfile:
    """Build a registration-only profile: no default, two members on one provider."""
    provider = ResolvedProvider(
        name="mock_p",
        protocol="openai",
        base_url="http://localhost:8800",
        api_key="mock_key",
        raw_api_key_ref="${KEY}",
    )
    m_a = ResolvedModel(model_id="a-upstream", provider=provider)
    m_b = ResolvedModel(model_id="b-upstream", provider=provider)
    return ResolvedProfile(
        profile_name="reg",
        models={"fast": m_a, "coder": m_b},
        default_model=None,
    )


def test_pi_registration_only_projects_models_but_not_settings(tmp_home: Path) -> None:
    """Pi registers every member; settings.json default fields stay untouched, and
    no `default` is a normal declaration state — no warning at all."""
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    models_file = pi_dir / "models.json"
    settings_file = pi_dir / "settings.json"
    settings_before = '{"defaultProvider": "user_own", "defaultModel": "user-model"}'
    settings_file.write_text(settings_before, encoding="utf-8")

    profile = make_registration_only_profile()
    ops, warnings = pi.plan(profile)

    # Only models.json providers ops — no settings.json ops at all.
    assert ops, "registration-only must still produce providers ops"
    assert all(op.file == models_file for op in ops)
    assert all(op.path.startswith("providers.") for op in ops)

    # No `default` is a normal state — zero warnings, never silent-but-unremarked
    # (there's simply nothing unexpressed to surface: registration succeeded fully).
    assert warnings == []

    res = write_changeset(
        agent_id=pi.AGENT_ID,
        profile_name="reg",
        allowed_paths=pi.config_paths(),
        allowed_namespaces=pi.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop

    content = models_file.read_text(encoding="utf-8")
    models_arr = json.loads(content)["providers"]["mock_p"]["models"]
    assert {m["name"]: m["id"] for m in models_arr} == {
        "fast": "a-upstream",
        "coder": "b-upstream",
    }

    # settings.json is byte-identical — user-owned defaults untouched.
    assert settings_file.read_text(encoding="utf-8") == settings_before


def test_pi_registration_only_idempotent(tmp_home: Path) -> None:
    """Re-planning after apply yields identical ops (idempotency holds)."""
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    (pi_dir / "settings.json").write_text("{}", encoding="utf-8")

    profile = make_registration_only_profile()
    ops, _ = pi.plan(profile)
    write_changeset(
        agent_id=pi.AGENT_ID,
        profile_name="reg",
        allowed_paths=pi.config_paths(),
        allowed_namespaces=pi.managed_namespaces(),
        ops=ops,
    )
    ops2, _ = pi.plan(profile)
    assert [(o.file.name, o.path, o.new) for o in ops2] == [
        (o.file.name, o.path, o.new) for o in ops
    ]


def test_claude_code_registration_only_nothing_to_project() -> None:
    """No registry channel + no default → empty ops with one explicit warning."""
    ops, warnings = claude_code.plan(make_registration_only_profile())
    assert ops == []
    assert any(
        "no model-registry channel" in w.reason and "nothing to project" in w.reason
        for w in warnings
    )


def test_codex_registration_only_nothing_to_project() -> None:
    """No registry channel + no default → empty ops with one explicit warning."""
    ops, warnings = codex.plan(make_registration_only_profile())
    assert ops == []
    assert any(
        "no model-registry channel" in w.reason and "nothing to project" in w.reason
        for w in warnings
    )


def test_pi_registration_only_settings_absent_ok(tmp_home: Path) -> None:
    """settings.json need not exist for a registration-only projection."""
    (tmp_home / ".pi" / "agent").mkdir(parents=True, exist_ok=True)

    profile = make_registration_only_profile()
    ops, _ = pi.plan(profile)
    res = write_changeset(
        agent_id=pi.AGENT_ID,
        profile_name="reg",
        allowed_paths=pi.config_paths(),
        allowed_namespaces=pi.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop
    assert not (tmp_home / ".pi" / "agent" / "settings.json").exists()
    parsed = json.loads((tmp_home / ".pi" / "agent" / "models.json").read_text())
    assert set(parsed["providers"]["mock_p"]["models"][0].keys()) >= {"id", "name"}
