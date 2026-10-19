import textwrap

import pytest
from fakes import team_manifest

from acm.catalog.manifest import parse_manifest, provider_from_manifest
from acm.catalog.model import Provider
from acm.catalog.resolve import (
    Catalog,
    TargetError,
    build_catalog,
    profile_providers,
    resolve_target,
)
from acm.catalog.static import static_provider
from acm.config.load import parse_config_text
from acm.config.refs import parse_credential
from acm.core.errors import ConfigError, IOFailureError

CFG = textwrap.dedent(
    """
    version: 4
    providers:
      ds:
        protocol: openai-completions
        base_url: https://api.deepseek.com/v1
        api_key: "${DS}"
        models:
          pro: {context_window: 1000000, roles: [default]}
          flash: {roles: [fast]}
      team:
        manifest: http://gw/manifest
        api_key: "${K}"
    profiles:
      static: {default: pro, roles: {fast: ds@fast}, models: {m: flash}}
      team:
        default: team@default
        roles: {reasoning: team@reasoning, fast: team@fast, subagent: team@subagent, review: team@review}
        models: {deep: team.agent}
      anth: {default: team.claude}
      bad: {default: team.nope}
    """
)
OAI = ("openai-completions",)
ANT = ("anthropic-messages",)
RESP = ("openai-responses",)


@pytest.fixture
def cfg():
    return parse_config_text(CFG)


@pytest.fixture
def cat(cfg):
    prov = provider_from_manifest(
        "team", parse_manifest(team_manifest("http://gw")), credential=parse_credential("${K}"),
        headers={}, source="s",
    )  # fmt: skip
    return Catalog(providers={"ds": static_provider("ds", cfg.providers["ds"]), "team": prov})


def test_static_profile(cfg, cat):
    t = resolve_target(cfg, cat, "static", OAI, "x")
    assert t.default.id == "pro" and t.default.protocol == "openai-completions"
    assert t.default.base_url == "https://api.deepseek.com/v1"
    assert t.role("fast").id == "flash" and t.role("default") is t.default
    assert t.members["m"].id == "flash"
    assert [m.id for m in t.all_models()] == ["pro", "flash"]


def test_manifest_roles_follow_the_agents_protocol(cfg, cat):
    openai = resolve_target(cfg, cat, "team", OAI, "codex-like")
    assert openai.default.id == "coding" and openai.default.base_url == "http://gw/v1"
    assert openai.role("reasoning").id == "agent"
    assert openai.role("fast").id == "cheap"
    anth = resolve_target(cfg, cat, "team", ANT, "claude")
    assert anth.default.id == "claude" and anth.default.base_url == "http://gw"
    assert anth.role("reasoning").id == "agent" and anth.role("fast").id == "cheap"
    resp = resolve_target(cfg, cat, "team", RESP, "codex")
    assert resp.default.id == "resp" and resp.default.protocol == "openai-responses"
    assert resp.role("review").id == "agent"
    assert resp.role("fast") is None  # no fast model on Responses -> warning, not failure
    assert any(w.field == "roles.fast" for w in resp.warnings)
    assert any(w.field == "roles.subagent" for w in resp.warnings)  # coding is not on Responses


def test_protocol_preference_order_decides(cfg, cat):
    t = resolve_target(cfg, cat, "team", ("anthropic-messages", "openai-completions"), "pi")
    assert t.default.id == "claude"
    t = resolve_target(cfg, cat, "team", ("openai-completions", "anthropic-messages"), "pi")
    assert t.default.id == "coding"


def test_default_unavailable_on_agent_protocol_is_target_error(cfg, cat):
    with pytest.raises(TargetError, match="cannot use"):
        resolve_target(cfg, cat, "static", ANT, "claude")
    with pytest.raises(TargetError, match="no model with role 'default'"):
        resolve_target(cfg, cat, "team", ("gemini",), "x")


def test_unknown_manifest_model_is_a_config_error(cfg, cat):
    with pytest.raises(ConfigError, match="not offered by provider 'team'"):
        resolve_target(cfg, cat, "bad", OAI, "x")


def test_failed_provider_error_is_raised(cfg):
    cat = Catalog(errors={"team": IOFailureError("down")})
    cat.providers["ds"] = static_provider("ds", cfg.providers["ds"])
    with pytest.raises(IOFailureError):
        resolve_target(cfg, cat, "team", OAI, "x")


def test_ambiguous_static_roles():
    cfg2 = parse_config_text(
        textwrap.dedent(
            """
            version: 4
            providers:
              ds:
                protocol: openai-completions
                base_url: https://x/v1
                models:
                  a: {roles: [default]}
                  b: {roles: [default]}
            profiles:
              p: {default: ds@default}
            """
        )
    )
    cat = Catalog(providers={"ds": static_provider("ds", cfg2.providers["ds"])})
    with pytest.raises(ConfigError, match="ambiguous"):
        resolve_target(cfg2, cat, "p", OAI, "x")


def test_profile_providers_and_build_catalog(ctx, cfg, gateway):
    assert profile_providers(cfg, "static") == {"ds"}
    assert profile_providers(cfg, "team") == {"team"}
    cat = build_catalog(ctx, cfg, needed={"ds"})
    assert set(cat.providers) == {"ds"} and not cat.errors
    gateway.stop()
    cfg2 = parse_config_text(CFG.replace("http://gw/manifest", gateway.url + "/manifest"))
    cat = build_catalog(ctx, cfg2)
    assert "team" in cat.errors and "ds" in cat.providers


def test_provider_without_cards_helpers(cfg):
    p: Provider = static_provider("ds", cfg.providers["ds"])
    assert p.primary_protocol == "openai-completions" and p.card("nope") is None
