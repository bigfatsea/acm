# // Ver 2026-08-26 00:00, by claude-sonnet-5
"""Unit tests for Core Config parsing and schema validation (schema v3)."""

from pathlib import Path

import pytest

from acm.config import CoreConfig, load_config, parse_config_yaml
from acm.errors import ConfigError


def test_valid_config_parsing(sample_config_yaml: str) -> None:
    """Test parsing a valid complete config.yaml."""
    cfg = parse_config_yaml(sample_config_yaml)
    assert cfg.version == 3
    assert "vmr" in cfg.providers
    assert cfg.providers["vmr"].protocol == "openai"
    assert cfg.providers["vmr"].base_url == "http://127.0.0.1:8800/v1"
    assert "coding" in cfg.providers["vmr"].models
    assert cfg.providers["vmr"].models["coding"].context_window == 131072
    assert cfg.providers["vmr"].models["coding"].reasoning is not None
    assert cfg.providers["vmr"].models["coding"].reasoning.effort == "high"
    assert "daily" in cfg.profiles
    assert cfg.profiles["daily"].default == "coding"
    assert cfg.profiles["daily"].models == {"coder": "coding"}


def test_invalid_version() -> None:
    """Test config with a v1-shaped (now unsupported) schema version."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      m: m
"""
    with pytest.raises(ConfigError, match="Unsupported config schema version: 1"):
        parse_config_yaml(yaml_str)


def test_missing_protocol() -> None:
    """Test provider missing protocol."""
    yaml_str = """version: 3
providers:
  p:
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      m: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


def test_invalid_protocol() -> None:
    """Test provider with unsupported protocol dialect."""
    yaml_str = """version: 3
providers:
  p:
    protocol: unsupported-protocol
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      m: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


def test_invalid_base_url() -> None:
    """Test provider with invalid base_url (no http/https)."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: ftp://invalid-url
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      m: m
"""
    with pytest.raises(ConfigError, match="base_url must start with http:// or https://"):
        parse_config_yaml(yaml_str)


def test_empty_profiles() -> None:
    """Test config without any profiles."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
"""
    with pytest.raises(ConfigError, match="must define at least one profile"):
        parse_config_yaml(yaml_str)


def test_load_config_file_not_found(tmp_path: Path) -> None:
    """Test loading non-existent config file."""
    with pytest.raises(ConfigError, match="Config file not found"):
        load_config(tmp_path / "non_existent.yaml")


def test_load_config_file_success(tmp_path: Path, sample_config_yaml: str) -> None:
    """Test loading config from actual file path."""
    p = tmp_path / "config.yaml"
    p.write_text(sample_config_yaml, encoding="utf-8")
    cfg = load_config(p)
    assert isinstance(cfg, CoreConfig)
    assert cfg.version == 3


# ── V1: provider name / model id charset ─────────────────────────────────────


def test_v1_provider_name_with_dot_rejected() -> None:
    """Provider names must not contain '.' — it is the qualified-reference separator."""
    yaml_str = """version: 3
providers:
  vmr.prod:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      x: m
"""
    with pytest.raises(ConfigError, match="must not contain '.'"):
        parse_config_yaml(yaml_str)


def test_v1_empty_provider_models_allowed() -> None:
    """A provider with zero models is legal (just unreachable via any reference)."""
    yaml_str = """version: 3
providers:
  empty:
    protocol: openai
    base_url: http://localhost
    api_key: k
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      x: m
"""
    cfg = parse_config_yaml(yaml_str)
    assert cfg.providers["empty"].models == {}


# ── V2: profile 'models' must be non-empty ───────────────────────────────────


def test_v2_profile_without_models_or_default_rejected() -> None:
    """A profile declaring neither `models` nor `default` is rejected."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d: {}
"""
    with pytest.raises(ConfigError, match="must declare at least one of 'models'"):
        parse_config_yaml(yaml_str)


def test_v2_empty_models_without_default_rejected() -> None:
    """An explicit but empty 'models: {}' with no 'default' is also rejected."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models: {}
"""
    with pytest.raises(ConfigError, match="must declare at least one of 'models'"):
        parse_config_yaml(yaml_str)


def test_v2_default_only_profile_valid() -> None:
    """A profile declaring only `default` (no `models`) is valid (selection-only)."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    default: m
"""
    cfg = parse_config_yaml(yaml_str)
    assert cfg.profiles["d"].default == "m"
    assert cfg.profiles["d"].models == {}


# ── V3: R3 reference resolution ───────────────────────────────────────────────


def _two_provider_yaml(daily_models_block: str) -> str:
    return f"""version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k
    models:
      coding: {{}}
      cheap: {{}}

  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: k2
    models:
      claude-sonnet: {{}}

profiles:
  daily:
{daily_models_block}
"""


def test_v3_qualified_ref_ok() -> None:
    """A qualified <provider>.<id> reference resolves."""
    cfg = parse_config_yaml(
        _two_provider_yaml("    models:\n      reviewer: anthropic-direct.claude-sonnet\n")
    )
    assert cfg.profiles["daily"].models == {"reviewer": "anthropic-direct.claude-sonnet"}


def test_v3_qualified_ref_unknown_provider() -> None:
    """A qualified reference to a non-existent provider is rejected."""
    with pytest.raises(ConfigError, match="provider 'ghost'.*is not defined"):
        parse_config_yaml(
            _two_provider_yaml("    models:\n      reviewer: ghost.claude-sonnet\n")
        )


def test_v3_qualified_ref_unknown_model() -> None:
    """A qualified reference to a non-existent model id under a real provider is rejected."""
    with pytest.raises(ConfigError, match="model id 'ghost' is not defined under provider 'vmr'"):
        parse_config_yaml(_two_provider_yaml("    models:\n      x: vmr.ghost\n"))


def test_v3_bare_ref_unique_ok() -> None:
    """A bare id that is globally unique resolves without qualification."""
    cfg = parse_config_yaml(_two_provider_yaml("    models:\n      coder: coding\n"))
    assert cfg.profiles["daily"].models == {"coder": "coding"}


def test_v3_bare_ref_unknown() -> None:
    """A bare id matching nothing anywhere is rejected."""
    with pytest.raises(ConfigError, match="unknown model id 'ghost'"):
        parse_config_yaml(_two_provider_yaml("    models:\n      x: ghost\n"))


def test_v3_bare_ref_ambiguous() -> None:
    """A bare id defined under two providers is rejected with all candidates listed."""
    yaml_str = """version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k
    models:
      sonnet: {}

  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: k2
    models:
      sonnet: {}

profiles:
  daily:
    models:
      coder: sonnet
"""
    with pytest.raises(
        ConfigError,
        match=r"model id 'sonnet' is ambiguous.*\['anthropic-direct', 'vmr'\].*"
        r"qualified reference like 'anthropic-direct.sonnet'",
    ):
        parse_config_yaml(yaml_str)


def test_v3_ref_with_dot_in_id_qualified() -> None:
    """A qualified ref whose id itself contains dots splits only on the first dot."""
    yaml_str = """version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k
    models:
      "gpt-4o.2": {}
profiles:
  daily:
    models:
      x: vmr.gpt-4o.2
"""
    cfg = parse_config_yaml(yaml_str)
    assert cfg.profiles["daily"].models == {"x": "vmr.gpt-4o.2"}


# ── V4: default is an independent R3 reference (not a member label) ──────────


def test_v4_default_resolves_bare_ref() -> None:
    """The default is an R3 ref resolved like a member value; it never needs to be a label."""
    cfg = parse_config_yaml(_two_provider_yaml("    default: coding\n"))
    assert cfg.profiles["daily"].default == "coding"


def test_v4_default_qualified_ref_ok() -> None:
    """A qualified <provider>.<id> default resolves."""
    cfg = parse_config_yaml(_two_provider_yaml("    default: vmr.coding\n"))
    assert cfg.profiles["daily"].default == "vmr.coding"


def test_v4_default_unknown_model_rejected() -> None:
    """A default naming a model id that exists nowhere is rejected."""
    with pytest.raises(ConfigError, match="default: unknown model id 'ghost'"):
        parse_config_yaml(_two_provider_yaml("    default: ghost\n"))


def test_v4_default_ambiguous_rejected() -> None:
    """A bare default id defined under two providers is ambiguous and rejected."""
    yaml_str = """version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k
    models:
      sonnet: {}

  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: k2
    models:
      sonnet: {}

profiles:
  daily:
    default: sonnet
"""
    with pytest.raises(ConfigError, match="default: model id 'sonnet' is ambiguous"):
        parse_config_yaml(yaml_str)


def test_v4_no_default_is_valid() -> None:
    """Omitting 'default' entirely is a normal, valid registration-only declaration."""
    cfg = parse_config_yaml(_two_provider_yaml("    models:\n      coder: coding\n"))
    assert cfg.profiles["daily"].default is None


# ── V5: same-profile members must not collapse onto the same upstream model ──


def test_v5_duplicate_upstream_within_profile_rejected() -> None:
    """Two labels resolving to the same (provider, id) pair are rejected."""
    with pytest.raises(
        ConfigError, match="both resolve to upstream model id 'coding' on provider 'vmr'"
    ):
        parse_config_yaml(
            _two_provider_yaml(
                "    models:\n      a: coding\n      b: vmr.coding\n"
            )
        )


def test_v5_same_id_different_providers_allowed() -> None:
    """Same upstream id string on *different* providers is not ambiguous when qualified."""
    yaml_str = """version: 3
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k
    models:
      cheap: {}

  direct:
    protocol: openai
    base_url: https://api.example.com/v1
    api_key: k2
    models:
      cheap: {}

profiles:
  daily:
    models:
      budget: vmr.cheap
      alt: direct.cheap
"""
    cfg = parse_config_yaml(yaml_str)
    assert cfg.profiles["daily"].models == {"budget": "vmr.cheap", "alt": "direct.cheap"}


# ── V6: version ────────────────────────────────────────────────────────────


def test_v6_wrong_version_rejected() -> None:
    yaml_str = """version: 2
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      x: m
"""
    with pytest.raises(ConfigError, match="Unsupported config schema version: 2"):
        parse_config_yaml(yaml_str)


# ── V8: extra=forbid rejects v1-shaped keys ───────────────────────────────────


def test_v8_top_level_models_key_rejected() -> None:
    """v1's top-level 'models:' table is gone; extra=forbid rejects it."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
models:
  m:
    provider: p
    id: m
profiles:
  d:
    models:
      x: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


@pytest.mark.parametrize("old_key", ["main", "cheap", "pool"])
def test_v8_profile_old_channel_keys_rejected(old_key: str) -> None:
    """v1's main:/cheap:/pool: profile keys are gone; extra=forbid rejects them."""
    yaml_str = f"""version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {{}}
profiles:
  d:
    models:
      x: m
    {old_key}: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


def test_v8_model_provider_id_fields_rejected() -> None:
    """v1's per-model provider:/id: fields are gone; extra=forbid rejects them."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m:
        provider: p
        id: m
profiles:
  d:
    models:
      x: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


# ── capabilities.thinking ─────────────────────────────────────────────────────


def test_capabilities_thinking_defaults_false() -> None:
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m: {}
profiles:
  d:
    models:
      x: m
"""
    cfg = parse_config_yaml(yaml_str)
    caps = cfg.providers["p"].models["m"].capabilities
    assert caps is None


def test_capabilities_thinking_settable_true() -> None:
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      m:
        capabilities:
          thinking: true
profiles:
  d:
    models:
      x: m
"""
    cfg = parse_config_yaml(yaml_str)
    caps = cfg.providers["p"].models["m"].capabilities
    assert caps is not None
    assert caps.thinking is True


# ── Non-string model-id keys: pydantic rejects, does NOT coerce ─────────────


def test_non_string_model_key_rejected() -> None:
    """An unquoted numeric YAML key is parsed as int by ruamel and pydantic then
    rejects it outright (ValidationError) rather than silently coercing to str."""
    yaml_str = """version: 3
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
    models:
      4: {}
profiles:
  d:
    models:
      x: coding
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)
