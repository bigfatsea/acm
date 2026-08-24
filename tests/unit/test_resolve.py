# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for ENV reference validation and ResolvedProfile evaluation (WP1)."""

import pytest

from acm.config import parse_config_toml
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


def test_resolve_profile_success(sample_config_toml: str) -> None:
    """Test full profile resolution with defaults/environment."""
    cfg = parse_config_toml(sample_config_toml)
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
    toml = """version = 1
[providers.p1]
protocol = "openai"
base_url = "http://localhost"
api_key = "${MISSING_KEY_1}"

[providers.p2]
protocol = "anthropic"
base_url = "http://localhost"
api_key = "${MISSING_KEY_2}"

[models.m1]
provider = "p1"
id = "m1"

[models.m2]
provider = "p2"
id = "m2"

[profiles.d]
main = "m1"
cheap = "m2"
"""
    cfg = parse_config_toml(toml)
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile("d", cfg, {})

    err_msg = str(excinfo.value)
    assert "${MISSING_KEY_1}" in err_msg
    assert "${MISSING_KEY_2}" in err_msg


def test_resolve_profile_ignores_unrelated_unexported_env_vars() -> None:
    """Test that missing env vars in unreferenced providers do NOT block the active profile."""
    toml = """version = 1
[providers.used_p]
protocol = "openai"
base_url = "http://localhost"
api_key = "plain-key"

[providers.unrelated_p]
protocol = "anthropic"
base_url = "http://localhost"
api_key = "${UNRELATED_UNSET_VAR}"

[models.used_m]
provider = "used_p"
id = "used"

[models.unrelated_m]
provider = "unrelated_p"
id = "unrelated"

[profiles.daily]
main = "used_m"
"""
    cfg = parse_config_toml(toml)
    # UNRELATED_UNSET_VAR is not exported, but daily only uses used_p -> must succeed!
    resolved = resolve_profile("daily", cfg, {})
    assert resolved.main.provider.name == "used_p"
    assert resolved.main.provider.api_key == "plain-key"


def test_resolve_profile_not_found(sample_config_toml: str) -> None:
    """Test resolution of non-existent profile name."""
    cfg = parse_config_toml(sample_config_toml)
    with pytest.raises(NotFoundError, match="Profile 'unknown' not found"):
        resolve_profile("unknown", cfg, {})
