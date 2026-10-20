import pytest
from fakes import team_manifest

from acm.catalog.probe import default_gateway_url, probe_gateway
from acm.catalog.proposal import proposal_for, provider_name, template_config
from acm.config.load import parse_config_text
from acm.core.context import Ctx


def test_probe_manifest(ctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    r = probe_gateway(ctx, gateway.url, "sk-test-key")
    assert r.outcome == "manifest" and r.manifest["gateway"]["kind"] == "vmr"


def test_probe_falls_back_to_models(ctx, gateway):
    gateway.models_list = [
        {"id": "coding", "vmr_protocol": "openai-completions"},
        {"id": "claude", "vmr_protocol": "anthropic-messages"},
        {"id": "plain"},
    ]
    r = probe_gateway(ctx, gateway.url, "sk-test-key")
    assert r.outcome == "models"
    assert r.models == [
        ("coding", "openai-completions"), ("claude", "anthropic-messages"),
        ("plain", "openai-completions"),
    ]  # fmt: skip


def test_probe_auth_required_and_none(ctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    assert probe_gateway(ctx, gateway.url, "wrong").outcome == "auth_required"
    assert probe_gateway(ctx, gateway.url, "").outcome == "auth_required"
    gateway.stop()
    assert probe_gateway(ctx, gateway.url, "x").outcome == "none"


def test_probe_rejects_unusable_manifest(ctx, gateway):
    gateway.manifest = {"manifest_version": 7}
    r = probe_gateway(ctx, gateway.url, "sk-test-key")
    assert r.outcome == "none" and "unusable" in r.detail


def test_default_gateway_url_precedence(ctx):
    assert default_gateway_url(ctx).startswith("http://127.0.0.1")
    c = Ctx.from_env({**ctx.env, "VMR_URL": "https://vmr.team.lan/"}, interactive=False)
    assert default_gateway_url(c) == "https://vmr.team.lan"


def test_manifest_proposal_is_a_valid_config(ctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    text = proposal_for(probe_gateway(ctx, gateway.url, "sk-test-key"))
    cfg = parse_config_text(text)
    assert cfg.providers["vmr"].is_manifest and cfg.providers["vmr"].api_key == "${VMR_KEY}"
    prof = cfg.profiles["daily"]
    assert prof.default == "vmr@default"
    assert prof.roles == {
        "reasoning": "vmr@reasoning", "fast": "vmr@fast", "subagent": "vmr@subagent",
        "review": "vmr@review",
    }  # fmt: skip
    assert "sk-test-key" not in text


def test_manifest_without_default_role_uses_first_model():
    from acm.catalog.probe import ProbeResult

    m = team_manifest()
    for model in m["models"]:
        model["roles"] = [r for r in model["roles"] if r != "default"]
    text = proposal_for(ProbeResult("manifest", "http://h", manifest=m))
    assert parse_config_text(text).profiles["daily"].default == "vmr.coding"


def test_models_proposal_groups_by_protocol():
    from acm.catalog.probe import ProbeResult

    probe = ProbeResult(
        "models", "http://h:8800",
        models=[("claude", "anthropic-messages"), ("coding", "openai-completions"),
                ("agent", "openai-completions")],
    )  # fmt: skip
    cfg = parse_config_text(proposal_for(probe))
    assert set(cfg.providers) == {"vmr", "vmr-anthropic"}
    assert cfg.providers["vmr"].base_url == "http://h:8800/v1"
    assert cfg.providers["vmr-anthropic"].base_url == "http://h:8800"
    assert cfg.profiles["daily"].default == "vmr.coding"


def test_template_and_names():
    cfg = parse_config_text(template_config())
    assert "anthropic" in cfg.providers and "daily" in cfg.profiles
    assert provider_name("my gateway!") == "my-gateway" and provider_name("!!") == "gateway"


@pytest.mark.parametrize("outcome", ["auth_required", "none"])
def test_no_discovery_gives_the_template(outcome):
    from acm.catalog.probe import ProbeResult

    assert proposal_for(ProbeResult(outcome, "http://h")) == template_config()


def test_keyless_gateway_gets_an_optional_key_reference(ctx):
    from acm.catalog.probe import ProbeResult

    m = team_manifest()
    m["auth"] = {"required": False}
    cfg = parse_config_text(proposal_for(ProbeResult("manifest", "http://h", manifest=m)))
    assert cfg.providers["vmr"].api_key == "${VMR_KEY:-}"  # an unset VMR_KEY must not block
    m["auth"] = {"required": True}
    cfg = parse_config_text(proposal_for(ProbeResult("manifest", "http://h", manifest=m)))
    assert cfg.providers["vmr"].api_key == "${VMR_KEY}"


def test_manifest_without_any_role_explains_and_lists_models():
    from acm.catalog.probe import ProbeResult

    m = team_manifest()
    for model in m["models"]:
        model["roles"] = []
    text = proposal_for(ProbeResult("manifest", "http://h", manifest=m))
    cfg = parse_config_text(text)
    assert cfg.profiles["daily"].default == "vmr.coding" and not cfg.profiles["daily"].roles
    assert "meta.roles" in text and "coding, claude, agent, cheap, resp" in text
