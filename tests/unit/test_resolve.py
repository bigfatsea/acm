# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Unit tests for ENV reference validation and ResolvedProfile evaluation (schema v3)."""

import pytest

from acm.config import parse_config_yaml
from acm.errors import ConfigError, NotFoundError
from acm.resolve import (
    evaluate_credential,
    resolve_profile,
    validate_credential_syntax,
)


def test_credential_syntax_valid() -> None:
    """Test valid credential syntax forms."""
    validate_credential_syntax("sk-plain-text")
    validate_credential_syntax("${VMR_KEY}")
    validate_credential_syntax("${VMR_KEY:-}")
    validate_credential_syntax("${VMR_KEY:-sk-fallback}")
    validate_credential_syntax("${OPENAI_API_KEY:-http://default.url}")


def test_credential_syntax_invalid() -> None:
    """Test invalid credential syntax rejection."""
    with pytest.raises(ConfigError, match="Invalid credential reference syntax"):
        validate_credential_syntax("prefix_${VAR}")

    with pytest.raises(ConfigError, match="Invalid credential reference syntax"):
        validate_credential_syntax("${VAR}_suffix")

    with pytest.raises(ConfigError, match="Invalid credential reference syntax"):
        validate_credential_syntax("${${NESTED}}")

    with pytest.raises(ConfigError, match="Invalid credential reference syntax"):
        validate_credential_syntax("${}")


def test_evaluate_credential_plain() -> None:
    """Test plain credential evaluation."""
    val, missing = evaluate_credential("plain-secret", {})
    assert val == "plain-secret"
    assert missing is None


def test_evaluate_credential_env_present() -> None:
    """Test env present evaluation."""
    val, missing = evaluate_credential("${MY_KEY}", {"MY_KEY": "secret-123"})
    assert val == "secret-123"
    assert missing is None


def test_evaluate_credential_env_fallback() -> None:
    """Test default fallback when env is missing."""
    val, missing = evaluate_credential("${MY_KEY:-fallback-secret}", {})
    assert val == "fallback-secret"
    assert missing is None


def test_evaluate_credential_env_missing() -> None:
    """Test missing env without default."""
    val, missing = evaluate_credential("${MY_KEY}", {})
    assert val == ""
    assert missing == "MY_KEY"


def test_resolve_profile_success(sample_config_yaml: str) -> None:
    """Test full profile resolution with defaults/environment."""
    cfg = parse_config_yaml(sample_config_yaml)
    env = {"VMR_KEY": "vmr-token-999"}
    resolved = resolve_profile("daily", cfg, env)

    assert resolved.profile_name == "daily"
    assert resolved.default_model is not None
    assert resolved.default_model.model_id == "coding"
    assert resolved.default_model.provider.name == "vmr"
    assert resolved.default_model.provider.api_key == "vmr-token-999"
    assert resolved.default_model.provider.base_url == "http://127.0.0.1:8800/v1"
    assert resolved.default_model.context_window == 131072
    assert resolved.default_model.reasoning is not None
    assert resolved.default_model.reasoning.effort == "high"
    # The default and the member labelled `coder` resolve to the SAME upstream model,
    # but they are distinct ResolvedModel objects (schema v3 resolves the default
    # independently); the shared provider object confirms key identity.
    assert resolved.models["coder"].provider is resolved.default_model.provider


def test_resolve_profile_missing_env_error() -> None:
    """Test hard error when required env vars for reachable providers are missing."""
    yaml_str = """version: 3
providers:
  p1:
    protocol: openai
    base_url: http://localhost
    api_key: "${MISSING_KEY_1}"
    models:
      m1: {}

  p2:
    protocol: anthropic
    base_url: http://localhost
    api_key: "${MISSING_KEY_2}"
    models:
      m2: {}

profiles:
  d:
    default: m1
    models:
      main: m1
      other: m2
"""
    cfg = parse_config_yaml(yaml_str)
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile("d", cfg, {})

    err_msg = str(excinfo.value)
    assert "${MISSING_KEY_1}" in err_msg
    assert "${MISSING_KEY_2}" in err_msg


def test_resolve_profile_ignores_unrelated_unexported_env_vars() -> None:
    """Test that missing env vars in unreferenced providers do NOT block the active profile."""
    yaml_str = """version: 3
providers:
  used_p:
    protocol: openai
    base_url: http://localhost
    api_key: plain-key
    models:
      used: {}

  unrelated_p:
    protocol: anthropic
    base_url: http://localhost
    api_key: "${UNRELATED_UNSET_VAR}"
    models:
      unrelated: {}

profiles:
  daily:
    default: used
    models:
      main: used
"""
    cfg = parse_config_yaml(yaml_str)
    # UNRELATED_UNSET_VAR is not exported, but daily only reaches used_p -> must succeed!
    resolved = resolve_profile("daily", cfg, {})
    assert resolved.default_model is not None
    assert resolved.default_model.provider.name == "used_p"
    assert resolved.default_model.provider.api_key == "plain-key"


def test_resolve_profile_not_found(sample_config_yaml: str) -> None:
    """Test resolution of non-existent profile name."""
    cfg = parse_config_yaml(sample_config_yaml)
    with pytest.raises(NotFoundError, match="Profile 'unknown' not found"):
        resolve_profile("unknown", cfg, {})


# ── Multi-provider members, ordering, and no-default (registration-only) ────

_MULTI_PROVIDER_YAML = """version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY}"
    models:
      coding: {}
      cheap: {}

  openai-direct:
    protocol: openai
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_KEY}"
    models:
      o3: {}

profiles:
  daily:
    default: coding
    models:
      main: coding
      budget: cheap
      review: openai-direct.o3
"""


def test_resolve_declared_order_preserved() -> None:
    """Member resolution order matches YAML declaration order."""
    cfg = parse_config_yaml(_MULTI_PROVIDER_YAML)
    resolved = resolve_profile("daily", cfg, {"VMR_KEY": "v", "OPENAI_KEY": "o"})

    assert list(resolved.models.keys()) == ["main", "budget", "review"]
    assert resolved.models["main"].model_id == "coding"
    assert resolved.models["budget"].model_id == "cheap"
    assert resolved.models["review"].model_id == "o3"
    assert resolved.models["review"].provider.name == "openai-direct"


def test_resolve_cross_provider_missing_env_aborts() -> None:
    """An unresolved ${VAR} on a member-only-reachable provider must hard-fail."""
    cfg = parse_config_yaml(_MULTI_PROVIDER_YAML)
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile("daily", cfg, {"VMR_KEY": "v"})  # OPENAI_KEY missing

    assert "${OPENAI_KEY}" in str(excinfo.value)


def test_resolve_no_default_profile(sample_config_yaml: str) -> None:
    """Registration-only profile (no default): default_model is None."""
    yaml_str = sample_config_yaml + """  reg:
    models:
      fast: coding
"""
    cfg = parse_config_yaml(yaml_str)
    rp = resolve_profile("reg", cfg, env={"VMR_KEY": "k"})
    assert rp.default_model is None
    assert list(rp.models.keys()) == ["fast"]
    assert rp.models["fast"].model_id == "coding"


_DEFAULT_ONLY_YAML = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: "${P_KEY}"
    models:
      m: {}

profiles:
  budget:
    default: m
"""


def test_resolve_default_only_provider_reachable_without_any_member() -> None:
    """default-only profile (no `models`): the default's provider must still be
    merged into the reachable set and have its credentials resolved, even though
    no member references it."""
    cfg = parse_config_yaml(_DEFAULT_ONLY_YAML)
    resolved = resolve_profile("budget", cfg, {"P_KEY": "secret"})

    assert resolved.models == {}
    assert resolved.default_model is not None
    assert resolved.default_model.model_id == "m"
    assert resolved.default_model.provider.name == "p"
    assert resolved.default_model.provider.api_key == "secret"


def test_resolve_default_only_missing_env_aborts() -> None:
    """default-only profile: an unresolved ${VAR} on the default's own provider must
    still hard-fail, even with an empty `models:` map."""
    cfg = parse_config_yaml(_DEFAULT_ONLY_YAML)
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile("budget", cfg, {})

    assert "${P_KEY}" in str(excinfo.value)
