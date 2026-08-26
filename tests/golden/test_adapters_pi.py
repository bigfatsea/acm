# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Golden tests for Pi adapter (schema v2): Apply, Non-destructive, Brand-new file creation & Rollback."""

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


def test_pi_multi_provider_registers_all_members(tmp_home: Path) -> None:
    """All members grouped by provider, label lands in 'name', default stays default."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    vmr = ResolvedProvider(
        name="vmr",
        protocol="openai",
        base_url="http://127.0.0.1:8800/v1",
        api_key="vmr-key",
        raw_api_key_ref="${VMR_KEY}",
    )
    openai_direct = ResolvedProvider(
        name="openai-direct",
        protocol="openai",
        base_url="https://api.openai.com/v1",
        api_key="oai-key",
        raw_api_key_ref="${OPENAI_KEY}",
    )
    coding = ResolvedModel(model_id="coding", provider=vmr, context_window=512000)
    cheap = ResolvedModel(model_id="cheap", provider=vmr)
    o3 = ResolvedModel(model_id="o3", provider=openai_direct)

    profile = ResolvedProfile(
        profile_name="daily",
        models={"main": coding, "budget": cheap, "review": o3},
        default_label="main",
    )

    ops, _warnings = pi.plan(profile, env={"VMR_KEY": "vmr-key", "OPENAI_KEY": "oai-key"})

    vmr_op = next(o for o in ops if o.path == "providers.vmr")
    assert vmr_op.new["models"] == [
        {"id": "coding", "name": "main", "contextWindow": 512000},
        {"id": "cheap", "name": "budget"},
    ]

    review_op = next(o for o in ops if o.path == "providers.openai-direct")
    assert review_op.new["models"] == [{"id": "o3", "name": "review"}]
    assert review_op.new["baseUrl"] == "https://api.openai.com/v1"

    # defaultProvider/defaultModel driven by the default member, unaffected by others
    settings_ops = {o.path: o.new for o in ops if o.path.startswith("default")}
    assert settings_ops["defaultProvider"] == "vmr"
    assert settings_ops["defaultModel"] == "coding"


def test_pi_non_default_member_temperature_warns_vision_projected() -> None:
    """A non-default member's temperature is an explicit, honestly-worded
    projection warning; capabilities.vision is *projected* into the model's
    `input` field (Pi's native channel), so it must not warn."""
    from acm.config import ModelCapabilities
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    vmr = ResolvedProvider(
        name="vmr", protocol="openai", base_url="http://127.0.0.1:8800/v1", api_key="k",
        raw_api_key_ref="${VMR_KEY}",
    )
    coding = ResolvedModel(model_id="coding", provider=vmr)
    cheap = ResolvedModel(
        model_id="cheap",
        provider=vmr,
        temperature=0.3,
        capabilities=ModelCapabilities(vision=True),
    )
    profile = ResolvedProfile(
        profile_name="daily", models={"main": coding, "budget": cheap}, default_label="main"
    )

    ops, warnings = pi.plan(profile, env={"VMR_KEY": "v"})

    temp_warns = [w for w in warnings if w.field == "models.budget.temperature"]
    assert len(temp_warns) == 1
    # Honest wording: Pi *can* express temperature via samplingParams on
    # OpenAI-compatible dialects; ACM simply does not project it yet — never a
    # blanket "Pi does not support" claim.
    assert "samplingParams" in temp_warns[0].reason
    assert "does not configure per-model temperature" not in temp_warns[0].reason

    # vision is projected into `input`, not warned about
    assert not any(w.field.startswith("models.budget.capabilities") for w in warnings)
    op = next(o for o in ops if o.path == "providers.vmr")
    budget_entry = next(m for m in op.new["models"] if m["name"] == "budget")
    assert budget_entry["input"] == ["text", "image"]


def test_pi_no_default_reasoning_warning_does_not_mention_default() -> None:
    """With no `default` at all, a member's reasoning warning must not claim
    "only the default's defaultThinkingLevel is projected" — there is no
    default, so nothing is projected for any member (R.3-G)."""
    from acm.config import ModelReasoning
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    vmr = ResolvedProvider(
        name="vmr", protocol="openai", base_url="http://127.0.0.1:8800/v1", api_key="k",
        raw_api_key_ref="${VMR_KEY}",
    )
    coding = ResolvedModel(
        model_id="coding", provider=vmr, reasoning=ModelReasoning(effort="high")
    )
    profile = ResolvedProfile(profile_name="reg", models={"main": coding}, default_label=None)

    ops, warnings = pi.plan(profile, env={"VMR_KEY": "v"})

    reasoning_warns = [w for w in warnings if w.field == "models.main.reasoning"]
    assert len(reasoning_warns) == 1
    assert "default's defaultThinkingLevel" not in reasoning_warns[0].reason
    assert "no default" in reasoning_warns[0].reason
    assert not any(o.path in ("defaultProvider", "defaultModel") for o in ops)


def test_pi_non_default_member_unexpressible_capabilities_warn() -> None:
    """Only genuinely unexpressible capability sub-fields warn — a
    non-native tool-calling dialect, json_mode and thinking have no Pi channel."""
    from acm.config import ModelCapabilities
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    vmr = ResolvedProvider(
        name="vmr", protocol="openai", base_url="http://127.0.0.1:8800/v1", api_key="k",
        raw_api_key_ref="${VMR_KEY}",
    )
    coding = ResolvedModel(model_id="coding", provider=vmr)
    cheap = ResolvedModel(
        model_id="cheap",
        provider=vmr,
        capabilities=ModelCapabilities(tools="xml", json_mode=True, thinking=True),
    )
    profile = ResolvedProfile(
        profile_name="daily", models={"main": coding, "budget": cheap}, default_label="main"
    )

    _, warnings = pi.plan(profile, env={"VMR_KEY": "v"})

    assert any(w.field == "models.budget.capabilities.tools" for w in warnings)
    assert any(w.field == "models.budget.capabilities.json_mode" for w in warnings)
    assert any(w.field == "models.budget.capabilities.thinking" for w in warnings)


def test_pi_default_temperature_honest_warning_and_vision_projected() -> None:
    """Default member's temperature warning is honestly worded (ACM does not
    project; Pi can via samplingParams), and its vision is projected into the
    model entry's `input` field — single-member path included."""
    from acm.config import ModelCapabilities
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    prov = ResolvedProvider(
        name="vmr", protocol="openai", base_url="http://127.0.0.1:8800/v1", api_key="k",
        raw_api_key_ref="${VMR_KEY}",
    )
    coding = ResolvedModel(
        model_id="coding",
        provider=prov,
        temperature=0.7,
        capabilities=ModelCapabilities(vision=True),
    )
    profile = ResolvedProfile(profile_name="daily", models={"main": coding}, default_label="main")

    ops, warnings = pi.plan(profile, env={"VMR_KEY": "v"})

    op = next(o for o in ops if o.path == "providers.vmr")
    assert op.new["models"][0]["input"] == ["text", "image"]

    temp_warns = [w for w in warnings if w.field == "temperature"]
    assert len(temp_warns) == 1
    assert "samplingParams" in temp_warns[0].reason
    assert not any(w.field == "capabilities" for w in warnings)


def test_pi_non_default_provider_headers_projected_proxy_warns() -> None:
    """Pi natively supports provider-level headers (confirmed against
    models.md's Provider Configuration table), so a non-default provider's
    headers must be *projected*, not warned about. Pi has no 'proxy' field at
    all, so proxy remains a genuine, explicitly-warned projection loss."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    vmr = ResolvedProvider(
        name="vmr", protocol="openai", base_url="http://127.0.0.1:8800/v1", api_key="k",
        raw_api_key_ref="${VMR_KEY}",
    )
    review_prov = ResolvedProvider(
        name="openai-direct",
        protocol="openai",
        base_url="https://api.openai.com/v1",
        api_key="oai",
        raw_api_key_ref="${OPENAI_KEY}",
        headers={"X-Custom": "1"},
        proxy="http://proxy.local:8080",
    )
    coding = ResolvedModel(model_id="coding", provider=vmr)
    o3 = ResolvedModel(model_id="o3", provider=review_prov)
    profile = ResolvedProfile(
        profile_name="daily", models={"main": coding, "review": o3}, default_label="main"
    )

    ops, warnings = pi.plan(profile, env={"VMR_KEY": "v", "OPENAI_KEY": "o"})

    review_op = next(o for o in ops if o.path == "providers.openai-direct")
    assert review_op.new["headers"] == {"X-Custom": "1"}

    assert not any(w.field == "models.provider.openai-direct.headers" for w in warnings)
    assert any(w.field == "models.provider.openai-direct.proxy" for w in warnings)
    # default's own provider (vmr) has no headers/proxy set here, so it must not
    # warn, and must not gain a spurious empty 'headers' key in its payload either.
    assert not any(w.field == "models.provider.vmr.proxy" for w in warnings)
    vmr_op = next(o for o in ops if o.path == "providers.vmr")
    assert "headers" not in vmr_op.new


def test_pi_default_provider_headers_projected(tmp_home: Path) -> None:
    """Default's own provider headers are projected (the shared warning would
    otherwise falsely claim Pi doesn't support headers at all — Pi's docs
    confirm it does)."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    prov = ResolvedProvider(
        name="vmr",
        protocol="openai",
        base_url="http://127.0.0.1:8800/v1",
        api_key="k",
        raw_api_key_ref="${VMR_KEY}",
        headers={"X-Org-Id": "acme"},
    )
    coding = ResolvedModel(model_id="coding", provider=prov)
    profile = ResolvedProfile(profile_name="daily", models={"main": coding}, default_label="main")

    ops, warnings = pi.plan(profile, env={"VMR_KEY": "v"})

    op = next(o for o in ops if o.path == "providers.vmr")
    assert op.new["headers"] == {"X-Org-Id": "acme"}
    assert not any(w.field == "provider.headers" for w in warnings)


def test_pi_apply_golden_non_destructive(tmp_home: Path) -> None:
    """Multi-member projection through the full Safety Engine pipeline: Apply /
    Non-destructive / Rollback-survives three-step golden assertion."""
    import hashlib

    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider
    from acm.state import get_snapshots_dir, load_last_write

    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "pi"
    models_fixture = (fixtures_dir / "models.golden.json").read_text(encoding="utf-8")
    initial_sha = hashlib.sha256(models_fixture.encode("utf-8")).hexdigest()
    pi_dir = tmp_home / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)
    models_file = pi_dir / "models.json"
    models_file.write_text(models_fixture, encoding="utf-8")

    vmr = ResolvedProvider(
        name="vmr", protocol="openai", base_url="http://127.0.0.1:8800/v1", api_key="k",
        raw_api_key_ref="${VMR_KEY}",
    )
    coding = ResolvedModel(model_id="coding", provider=vmr)
    cheap = ResolvedModel(model_id="cheap", provider=vmr)
    profile = ResolvedProfile(
        profile_name="daily", models={"main": coding, "budget": cheap}, default_label="main"
    )

    ops, _ = pi.plan(profile, env={"VMR_KEY": "v"})

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

    updated_content = models_file.read_text(encoding="utf-8")
    assert read_json_path(updated_content, "providers.vmr.models") == [
        {"id": "coding", "name": "main"},
        {"id": "cheap", "name": "budget"},
    ]
    # Unrelated pre-existing provider entry survives untouched
    assert (
        read_json_path(updated_content, "providers.existing_provider.baseUrl")
        == "https://api.existing.com/v1"
    )

    # ── Step b: Non-destructive assertion ──────────────────────
    diffs = tree_diff(json.loads(models_fixture), json.loads(updated_content), pi.managed_namespaces())
    assert diffs == []

    # ── Step c: Rollback survives (physical snapshot restores pre-projection state) ──
    lw = load_last_write(pi.AGENT_ID)
    assert lw is not None
    snap_file = get_snapshots_dir(pi.AGENT_ID) / lw.backup_id / "models.json"
    assert snap_file.exists()

    models_file.write_bytes(snap_file.read_bytes())
    restored_sha = hashlib.sha256(models_file.read_bytes()).hexdigest()
    assert restored_sha == initial_sha


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
    model = ResolvedModel(model_id="coding", provider=keyless_p)
    profile = ResolvedProfile(profile_name="daily", models={"main": model}, default_label="main")

    ops, warnings = pi.plan(profile)
    op = next(o for o in ops if o.path == "providers.vmr")
    assert op.new["apiKey"] == "dummy"
    assert any(w.field == "provider.api_key" for w in warnings)
