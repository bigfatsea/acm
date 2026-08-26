# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for ENV reference validation and ResolvedProfile evaluation (WP1)."""

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
    assert resolved.main.model_id == "coding"
    assert resolved.main.upstream_id == "coding"
    assert resolved.main.provider.name == "vmr"
    assert resolved.main.provider.api_key == "vmr-token-999"
    assert resolved.main.provider.base_url == "http://127.0.0.1:8800/v1"
    assert resolved.main.context_window == 131072
    assert resolved.main.reasoning is not None
    assert resolved.main.reasoning.effort == "high"


def test_resolve_profile_missing_env_error() -> None:
    """Test hard error when required env vars for reachable providers are missing."""
    yaml_str = """version: 1
providers:
  p1:
    protocol: openai
    base_url: http://localhost
    api_key: "${MISSING_KEY_1}"

  p2:
    protocol: anthropic
    base_url: http://localhost
    api_key: "${MISSING_KEY_2}"

models:
  m1:
    provider: p1
    id: m1

  m2:
    provider: p2
    id: m2

profiles:
  d:
    main: m1
    cheap: m2
"""
    cfg = parse_config_yaml(yaml_str)
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile("d", cfg, {})

    err_msg = str(excinfo.value)
    assert "${MISSING_KEY_1}" in err_msg
    assert "${MISSING_KEY_2}" in err_msg


def test_resolve_profile_ignores_unrelated_unexported_env_vars() -> None:
    """Test that missing env vars in unreferenced providers do NOT block the active profile."""
    yaml_str = """version: 1
providers:
  used_p:
    protocol: openai
    base_url: http://localhost
    api_key: plain-key

  unrelated_p:
    protocol: anthropic
    base_url: http://localhost
    api_key: "${UNRELATED_UNSET_VAR}"

models:
  used_m:
    provider: used_p
    id: used

  unrelated_m:
    provider: unrelated_p
    id: unrelated

profiles:
  daily:
    main: used_m
"""
    cfg = parse_config_yaml(yaml_str)
    # UNRELATED_UNSET_VAR is not exported, but daily only uses used_p -> must succeed!
    resolved = resolve_profile("daily", cfg, {})
    assert resolved.main.provider.name == "used_p"
    assert resolved.main.provider.api_key == "plain-key"


def test_resolve_profile_not_found(sample_config_yaml: str) -> None:
    """Test resolution of non-existent profile name."""
    cfg = parse_config_yaml(sample_config_yaml)
    with pytest.raises(NotFoundError, match="Profile 'unknown' not found"):
        resolve_profile("unknown", cfg, {})


# ── Model pool resolution (DESIGN_MODEL_POOL_v1.md §8.2) ───────────────────

_POOL_MULTI_PROVIDER_YAML = """version: 1
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY}"

  openai-direct:
    protocol: openai
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_KEY}"

models:
  coding:
    provider: vmr
    id: coding

  cheap:
    provider: vmr
    id: cheap

  o3:
    provider: openai-direct
    id: o3

profiles:
  daily:
    main: coding
    pool:
      budget: cheap
      review: o3
"""


def test_resolve_pool_implicit_main_prepended() -> None:
    """R2: main is implicitly inserted at pool head under label 'main' when absent."""
    cfg = parse_config_yaml(_POOL_MULTI_PROVIDER_YAML)
    resolved = resolve_profile("daily", cfg, {"VMR_KEY": "v", "OPENAI_KEY": "o"})

    assert list(resolved.pool.keys()) == ["main", "budget", "review"]
    assert resolved.pool["main"].model_id == "coding"
    assert resolved.pool["budget"].model_id == "cheap"
    assert resolved.pool["review"].model_id == "o3"
    assert resolved.pool["review"].provider.name == "openai-direct"


def test_resolve_pool_explicit_main_not_duplicated() -> None:
    """R2: if a pool label already targets the same alias as main, no implicit dup is added."""
    yaml_str = _POOL_MULTI_PROVIDER_YAML.replace(
        "      budget: cheap",
        "      primary: coding\n      budget: cheap",
    )
    cfg = parse_config_yaml(yaml_str)
    resolved = resolve_profile("daily", cfg, {"VMR_KEY": "v", "OPENAI_KEY": "o"})

    assert list(resolved.pool.keys()) == ["primary", "budget", "review"]


def test_resolve_pool_cross_provider_missing_env_aborts() -> None:
    """R1 fix: an unresolved ${VAR} on a pool-only-reachable provider must hard-fail."""
    cfg = parse_config_yaml(_POOL_MULTI_PROVIDER_YAML)
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile("daily", cfg, {"VMR_KEY": "v"})  # OPENAI_KEY missing

    assert "${OPENAI_KEY}" in str(excinfo.value)


def test_resolve_pool_implicit_main_collision_with_explicit_alias_rejected() -> None:
    """Second-round review finding: config.py's E5 check only sees explicitly
    declared pool entries, so an implicitly-inserted main (R2) that collides on
    upstream id with a *different* explicit alias would slip past config-time
    validation. resolve_profile() must catch it as a defense-in-depth re-check."""
    yaml_str = """version: 1
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k

models:
  coding:
    provider: vmr
    id: same-id

  replica:
    provider: vmr
    id: same-id

profiles:
  daily:
    main: coding
    pool:
      replica_label: replica
"""
    cfg = parse_config_yaml(yaml_str)
    with pytest.raises(
        ConfigError, match="both resolve to upstream model id 'same-id' on provider 'vmr'"
    ):
        resolve_profile("daily", cfg, {})


def test_resolve_pool_empty_dict_is_absent() -> None:
    """R7: an empty pool map resolves to an empty pool (no implicit main insertion)."""
    yaml_str = """version: 1
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k

models:
  coding:
    provider: vmr
    id: coding

profiles:
  daily:
    main: coding
    pool: {}
"""
    cfg = parse_config_yaml(yaml_str)
    resolved = resolve_profile("daily", cfg, {})
    assert resolved.pool == {}


def test_resolve_pool_only_profile_no_implicit_main(sample_config_yaml: str) -> None:
    """Registration-only profile (no main): pool has no implicit 'main' member (§18 R2)."""
    yaml_str = sample_config_yaml + """  reg:
    pool:
      fast: coding
"""
    cfg = parse_config_yaml(yaml_str)
    rp = resolve_profile("reg", cfg, env={"VMR_KEY": "k"})
    assert rp.main is None
    assert list(rp.pool.keys()) == ["fast"]
    assert rp.pool["fast"].upstream_id == "coding"


def test_resolve_with_main_still_prepends_implicit_main_member(sample_config_yaml: str) -> None:
    """With main declared and absent from the pool, the implicit 'main' member remains."""
    yaml_str = sample_config_yaml + """  withmain:
    main: coding
    pool:
      extra: claude-sonnet
"""
    cfg = parse_config_yaml(yaml_str)
    rp = resolve_profile("withmain", cfg, env={"VMR_KEY": "k", "ANTHROPIC_API_KEY": "a"})
    assert rp.main is not None
    assert list(rp.pool.keys()) == ["main", "extra"]
