# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Golden tests for Pi adapter (WP8): Apply, Non-destructive, Brand-new file creation & Rollback."""

import json
from pathlib import Path

from conftest import make_mock_profile

from acm.adapters import pi
from acm.safety import write_changeset
from acm.writers.json_editor import read_json_path
from acm.writers.tree_diff import tree_diff


def test_pi_golden_existing_models(tmp_home: Path) -> None:
    """Test Pi adapter projection when models.json and settings.json already exist."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "pi"
    settings_fixture = (fixtures_dir / "settings.golden.json").read_text(encoding="utf-8")
    models_fixture = (fixtures_dir / "models.golden.json").read_text(encoding="utf-8")

    # Setup agent dir
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    models_file = pi_dir / "models.json"
    settings_file = pi_dir / "settings.json"
    models_file.write_text(models_fixture, encoding="utf-8")
    settings_file.write_text(settings_fixture, encoding="utf-8")

    profile = make_mock_profile(model_id="pi-coding-model")
    ops, _warnings = pi.plan(profile)

    # ── Step a: Apply ─────────────────────────────────────────
    res = write_changeset(
        agent_id=pi.AGENT_ID,
        profile_name="daily",
        allowed_paths=pi.config_paths(),
        allowed_namespaces=pi.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop
    assert res.backup_id is not None

    # Check models.json
    models_content = models_file.read_text(encoding="utf-8")
    assert read_json_path(models_content, "providers.mock_p.baseUrl") == "http://localhost:8800"
    assert (
        read_json_path(models_content, "providers.existing_provider.baseUrl")
        == "https://api.existing.com/v1"
    )

    # Check settings.json
    settings_content = settings_file.read_text(encoding="utf-8")
    assert read_json_path(settings_content, "defaultProvider") == "mock_p"
    assert read_json_path(settings_content, "defaultModel") == "pi-coding-model"

    # ── Step b: Non-destructive assertion ──────────────────────
    parsed_before = json.loads(settings_fixture)
    parsed_after = json.loads(settings_content)
    diffs = tree_diff(parsed_before, parsed_after, pi.managed_namespaces())
    assert diffs == []
    assert read_json_path(settings_content, "customSetting") == "keep_this_custom_val"


def test_pi_golden_brand_new_models_file(tmp_home: Path) -> None:
    """Test Pi adapter creating models.json from scratch and verifying safe orphan handling."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "pi"
    settings_fixture = (fixtures_dir / "settings.golden.json").read_text(encoding="utf-8")

    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    models_file = pi_dir / "models.json"
    settings_file = pi_dir / "settings.json"
    settings_file.write_text(settings_fixture, encoding="utf-8")

    # models.json does NOT exist initially
    assert not models_file.exists()

    profile = make_mock_profile(model_id="pi-coding-model")
    ops, _ = pi.plan(profile, env={"KEY": "secret_key_in_env"})

    res = write_changeset(
        agent_id=pi.AGENT_ID,
        profile_name="daily",
        allowed_paths=pi.config_paths(),
        allowed_namespaces=pi.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop
    assert models_file.exists()
    assert (
        read_json_path(models_file.read_text(encoding="utf-8"), "providers.mock_p.baseUrl")
        == "http://localhost:8800"
    )
    assert (
        read_json_path(models_file.read_text(encoding="utf-8"), "providers.mock_p.apiKey") == "$KEY"
    )


def test_pi_fallback_key_when_env_missing(tmp_home: Path) -> None:
    """Test Pi adapter writes evaluated fallback key when environment variable is not exported."""
    profile = make_mock_profile(model_id="pi-coding-model")
    # env without "KEY"
    ops, _ = pi.plan(profile, env={})
    op = next(o for o in ops if o.path == "providers.mock_p")
    assert op.new["apiKey"] == "mock_key"


def test_pi_keyless_uses_dummy_api_key(tmp_home: Path) -> None:
    """Test Pi adapter produces 'dummy' apiKey when key is empty."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    keyless_p = ResolvedProvider(
        name="vmr",
        protocol="openai",
        base_url="http://127.0.0.1:8800/v1",
        api_key="",
        raw_api_key_ref="",
    )
    model = ResolvedModel(model_id="coding", upstream_id="coding", provider=keyless_p)
    profile = ResolvedProfile(profile_name="daily", main=model)

    ops, warnings = pi.plan(profile)
    op = next(o for o in ops if o.path == "providers.vmr")
    assert op.new["apiKey"] == "dummy"
    assert any(w.field == "provider.api_key" for w in warnings)
