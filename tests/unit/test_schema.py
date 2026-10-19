import pytest

from acm.config.load import load_config, parse_config_text
from acm.config.refs import ModelRef, RoleRef
from acm.core.errors import ConfigError

STATIC = """
version: 4
providers:
  ds:
    protocol: openai-completions
    base_url: https://api.deepseek.com/v1/
    api_key: "${DS_KEY}"
    models:
      deepseek-v4-pro: {context_window: 1000000, roles: [fast]}
      gpt-4.1: {}
  team:
    manifest: https://vmr.team.lan/manifest
    api_key: "${VMR_KEY}"
profiles:
  daily:
    default: deepseek-v4-pro
    roles: {fast: "team@fast", reasoning: "ds@fast"}
    models: {pro: ds.deepseek-v4-pro, other: "team.agent"}
"""


def test_valid_config_and_normalization():
    cfg = parse_config_text(STATIC)
    assert cfg.providers["ds"].base_url == "https://api.deepseek.com/v1"
    assert cfg.providers["team"].is_manifest
    assert cfg.check_ref("deepseek-v4-pro") == ModelRef("ds", "deepseek-v4-pro")
    assert cfg.check_ref("team@fast") == RoleRef("team", "fast")
    assert cfg.check_ref("gpt-4.1") == ModelRef("ds", "gpt-4.1")


@pytest.mark.parametrize(
    ("patch", "needle"),
    [
        ("version: 3", "unsupported config version"),
        ("version: 4\nproviders: {}\nprofiles: {}", "at least one provider"),
        (STATIC.replace("protocol: openai-completions", "protocol: openai"), "protocol"),
        (STATIC.replace("default: deepseek-v4-pro", "default: nope"), "unknown model"),
        (STATIC.replace("ds@fast", "ds@review"), "no model with role"),
        (STATIC.replace('api_key: "${DS_KEY}"', 'api_key: "x${A}"'), "invalid credential"),
        (
            STATIC.replace("team.agent", "gpt-4.1").replace(
                "pro: ds.deepseek-v4-pro", "pro: ds.gpt-4.1"
            ),
            "same model",
        ),
        (
            STATIC.replace(
                "    manifest: https://vmr.team.lan/manifest",
                "    manifest: x\n    protocol: openai-completions",
            ),
            "cannot declare",
        ),
        (
            STATIC.replace(
                '    roles: {fast: "team@fast", reasoning: "ds@fast"}',
                '    roles: {planner: "team@fast"}',
            ),
            "unknown profile role",
        ),
        (STATIC.replace("ds:\n    protocol", "d.s:\n    protocol"), "invalid provider name"),
    ],
)
def test_invalid_configs(patch, needle):
    with pytest.raises(ConfigError, match=needle):
        parse_config_text(patch)


def test_ambiguous_bare_id():
    text = """
    version: 4
    providers:
      a: {protocol: openai-completions, base_url: "http://x/v1", models: {m: {}}}
      b: {protocol: openai-completions, base_url: "http://y/v1", models: {m: {}}}
    profiles:
      p: {default: m}
    """
    import textwrap

    with pytest.raises(ConfigError, match="ambiguous"):
        parse_config_text(textwrap.dedent(text))


def test_load_config_missing_and_present(ctx, make_config):
    with pytest.raises(ConfigError, match="acm init"):
        load_config(ctx)
    make_config(STATIC)
    assert "daily" in load_config(ctx).profiles


def test_roles_require_default_and_profile_needs_something():
    base = "version: 4\nproviders:\n  a: {protocol: openai-completions, base_url: 'http://x/v1', models: {m: {roles: [fast]}}}\nprofiles:\n  p: "
    with pytest.raises(ConfigError, match="'roles' requires 'default'"):
        parse_config_text(base + "{roles: {fast: 'a@fast'}, models: {x: m}}")
    with pytest.raises(ConfigError, match="must declare"):
        parse_config_text(base + "{}")
