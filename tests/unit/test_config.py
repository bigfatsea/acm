# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for Core Config parsing and schema validation (WP1)."""

from pathlib import Path

import pytest

from acm.config import CoreConfig, load_config, parse_config_yaml
from acm.errors import ConfigError


def test_valid_config_parsing(sample_config_yaml: str) -> None:
    """Test parsing a valid complete config.yaml."""
    cfg = parse_config_yaml(sample_config_yaml)
    assert cfg.version == 1
    assert "vmr" in cfg.providers
    assert cfg.providers["vmr"].protocol == "openai"
    assert cfg.providers["vmr"].base_url == "http://127.0.0.1:8800/v1"
    assert "coding" in cfg.models
    assert cfg.models["coding"].provider == "vmr"
    assert cfg.models["coding"].context_window == 131072
    assert cfg.models["coding"].reasoning is not None
    assert cfg.models["coding"].reasoning.effort == "high"
    assert "daily" in cfg.profiles
    assert cfg.profiles["daily"].main == "coding"


def test_invalid_version() -> None:
    """Test config with invalid schema version."""
    yaml_str = """version: 2
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
    main: m
"""
    with pytest.raises(ConfigError, match="Unsupported config schema version: 2"):
        parse_config_yaml(yaml_str)


def test_missing_protocol() -> None:
    """Test provider missing protocol."""
    yaml_str = """version: 1
providers:
  p:
    base_url: http://localhost
    api_key: k
models:
  m:
    provider: p
    id: m
profiles:
  d:
    main: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


def test_invalid_protocol() -> None:
    """Test provider with unsupported protocol dialect."""
    yaml_str = """version: 1
providers:
  p:
    protocol: unsupported-protocol
    base_url: http://localhost
    api_key: k
models:
  m:
    provider: p
    id: m
profiles:
  d:
    main: m
"""
    with pytest.raises(ConfigError):
        parse_config_yaml(yaml_str)


def test_invalid_base_url() -> None:
    """Test provider with invalid base_url (no http/https)."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: ftp://invalid-url
    api_key: k
models:
  m:
    provider: p
    id: m
profiles:
  d:
    main: m
"""
    with pytest.raises(ConfigError, match="base_url must start with http:// or https://"):
        parse_config_yaml(yaml_str)


def test_model_missing_provider() -> None:
    """Test model referencing non-existent provider."""
    yaml_str = """version: 1
providers:
  p1:
    protocol: openai
    base_url: http://localhost
    api_key: k
models:
  m:
    provider: non_existent_provider
    id: m
profiles:
  d:
    main: m
"""
    with pytest.raises(ConfigError, match="references non-existent provider"):
        parse_config_yaml(yaml_str)


def test_profile_missing_main_model() -> None:
    """Test profile referencing non-existent main model."""
    yaml_str = """version: 1
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
    main: non_existent_model
"""
    with pytest.raises(ConfigError, match="main model 'non_existent_model' is not defined"):
        parse_config_yaml(yaml_str)


def test_profile_missing_cheap_model() -> None:
    """Test profile referencing non-existent cheap model."""
    yaml_str = """version: 1
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
    main: m
    cheap: unknown_cheap
"""
    with pytest.raises(ConfigError, match="cheap model 'unknown_cheap' is not defined"):
        parse_config_yaml(yaml_str)


def test_empty_profiles() -> None:
    """Test config without any profiles."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
models:
  m:
    provider: p
    id: m
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
    assert cfg.version == 1


# ── Model pool ──────────────────────────────────────────────────────────


def _pool_base_yaml(daily_body: str) -> str:
    return f"""version: 1
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k

models:
  coding:
    provider: vmr
    id: coding

  cheap:
    provider: vmr
    id: cheap

  agent:
    provider: vmr
    id: agent

profiles:
  daily:
{daily_body}
"""


def test_pool_valid_parses() -> None:
    """A well-formed pool map parses and is exposed on ProfileConfig."""
    cfg = parse_config_yaml(
        _pool_base_yaml(
            """    main: coding
    pool:
      budget: cheap
      longctx: agent
"""
        )
    )
    assert cfg.profiles["daily"].pool == {"budget": "cheap", "longctx": "agent"}


def test_pool_empty_map_is_valid() -> None:
    """R7: pool = {} is valid and treated as if unset."""
    cfg = parse_config_yaml(_pool_base_yaml("    main: coding\n    pool: {}\n"))
    assert cfg.profiles["daily"].pool == {}


def test_pool_and_cheap_coexist() -> None:
    """D4: pool and cheap role are independent and may both be declared."""
    cfg = parse_config_yaml(
        _pool_base_yaml(
            """    main: coding
    cheap: cheap
    pool:
      budget: cheap
"""
        )
    )
    assert cfg.profiles["daily"].cheap == "cheap"
    assert cfg.profiles["daily"].pool == {"budget": "cheap"}


def test_pool_e1_unknown_model_alias() -> None:
    """E1: pool value referencing a non-existent model alias is rejected."""
    with pytest.raises(ConfigError, match="references non-existent model 'nonexistent'"):
        parse_config_yaml(
            _pool_base_yaml(
                """    main: coding
    pool:
      budget: nonexistent
"""
            )
        )


def test_pool_e2_duplicate_alias() -> None:
    """E2: two labels pointing at the same model alias is rejected."""
    with pytest.raises(ConfigError, match="Duplicate model alias 'cheap' in pool"):
        parse_config_yaml(
            _pool_base_yaml(
                """    main: coding
    pool:
      budget: cheap
      thrifty: cheap
"""
            )
        )


def test_pool_e3_empty_label() -> None:
    """E3: an empty-string label is rejected."""
    with pytest.raises(ConfigError, match="Pool label must be non-empty"):
        parse_config_yaml(
            _pool_base_yaml(
                """    main: coding
    pool:
      "": cheap
"""
            )
        )


def test_pool_e4_non_string_value_rejected() -> None:
    """E4: a nested mapping as a pool value is rejected by the dict[str, str] type."""
    with pytest.raises(ConfigError):
        parse_config_yaml(
            _pool_base_yaml(
                """    main: coding
    pool:
      budget:
        nested: not-a-string
"""
            )
        )


def test_pool_e5_duplicate_upstream_id_rejected() -> None:
    """Two distinct aliases resolving to the same (provider, id) pair are rejected —
    same-alias dedup alone doesn't catch this, and it would produce ambiguous
    duplicate-id entries in Pi's models[] array."""
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

  cheap:
    provider: vmr
    id: cheap

  agent:
    provider: vmr
    id: agent

  cheap-alias:
    provider: vmr
    id: cheap

profiles:
  daily:
    main: coding
    pool:
      budget: cheap
      thrifty: cheap-alias
"""
    with pytest.raises(
        ConfigError, match="both resolve to upstream model id 'cheap' on provider 'vmr'"
    ):
        parse_config_yaml(yaml_str)


def test_pool_distinct_upstream_ids_across_providers_allowed() -> None:
    """Same upstream id string on *different* providers is not ambiguous — allowed."""
    yaml_str = """version: 1
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: k

  direct:
    protocol: openai
    base_url: https://api.example.com/v1
    api_key: k2

models:
  coding:
    provider: vmr
    id: coding

  cheap:
    provider: vmr
    id: cheap

  agent:
    provider: vmr
    id: agent

  direct-cheap:
    provider: direct
    id: cheap

profiles:
  daily:
    main: coding
    pool:
      budget: cheap
      alt: direct-cheap
"""
    cfg = parse_config_yaml(yaml_str)
    assert cfg.profiles["daily"].pool == {"budget": "cheap", "alt": "direct-cheap"}


# ── Pool-only profiles (registration-only) ───────────────────────────────────

POOL_ONLY_YAML = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost:8800/v1
    api_key: k
models:
  a:
    provider: p
    id: a
  b:
    provider: p
    id: b
profiles:
  reg:
    pool:
      fast: a
      coder: b
"""


def test_pool_only_profile_valid() -> None:
    """A profile with no main but a non-empty pool is valid (registration-only)."""
    cfg = parse_config_yaml(POOL_ONLY_YAML)
    assert cfg.profiles["reg"].main is None
    assert cfg.profiles["reg"].pool == {"fast": "a", "coder": "b"}


def test_profile_without_main_and_pool_rejected() -> None:
    """Schema rule: main and pool must not both be absent."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost:8800/v1
    api_key: k
models:
  m:
    provider: p
    id: m
profiles:
  d: {}
"""
    with pytest.raises(ConfigError, match="must define either 'main' or a non-empty"):
        parse_config_yaml(yaml_str)
