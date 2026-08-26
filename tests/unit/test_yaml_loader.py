# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests pinning the YAML loader contract for ACM's Core Config.

Each test corresponds to a row of the loader-behavior table in
docs/ACM_PROJECT_SPEC_v2.1.md §6 D3:
- YAML 1.2 semantics via the ruamel safe loader (no yes/no/on/off coercion)
- duplicate keys are hard errors (fail-fast, never silently dropped)
- anchors/merge keys are allowed and safely resolved
- multi-document input is rejected
"""

import pytest

from acm.config import parse_config_yaml
from acm.errors import ConfigError


def _base(profiles_block: str) -> str:
    """Minimal valid config with the given profiles block."""
    return (
        """version: 1
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
"""
        + profiles_block
    )


def test_duplicate_keys_rejected() -> None:
    """Duplicate mapping keys fail loudly instead of silently keeping the last one."""
    content = _base("  d:\n    main: m\n") + "extra:\n  a: 1\n  a: 2\n"
    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        parse_config_yaml(content)


def test_on_off_yes_no_are_plain_strings() -> None:
    """YAML 1.2: on/off/yes/no stay strings — no boolean coercion anywhere."""
    yaml_str = """version: 1
providers:
  on:
    protocol: openai
    base_url: http://localhost
    api_key: k
models:
  m:
    provider: on
    id: yes
profiles:
  d:
    main: m
"""
    cfg = parse_config_yaml(yaml_str)
    assert cfg.models["m"].id == "yes"
    assert cfg.providers[cfg.models["m"].provider].protocol == "openai"


def test_true_false_still_boolean() -> None:
    """true/false resolve to real booleans for pydantic bool fields."""
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
    capabilities:
      vision: true
      json_mode: false
profiles:
  d:
    main: m
"""
    caps = parse_config_yaml(yaml_str).models["m"].capabilities
    assert caps is not None
    assert caps.vision is True
    assert caps.json_mode is False


def test_credential_ref_unquoted_parses() -> None:
    """${VAR} values survive parsing verbatim even unquoted."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: ${MY_KEY}
models:
  m:
    provider: p
    id: m
profiles:
  d:
    main: m
"""
    assert parse_config_yaml(yaml_str).providers["p"].api_key == "${MY_KEY}"


def test_credential_ref_default_syntax() -> None:
    """${VAR:-default} survives parsing verbatim."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: ${MY_KEY:-sk-fallback}
models:
  m:
    provider: p
    id: m
profiles:
  d:
    main: m
"""
    assert parse_config_yaml(yaml_str).providers["p"].api_key == "${MY_KEY:-sk-fallback}"


def test_multi_document_rejected() -> None:
    """A stream of multiple YAML documents is rejected, not silently truncated."""
    content = _base("  d:\n    main: m\n") + "---\nversion: 9\n"
    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        parse_config_yaml(content)


def test_empty_file_friendly_error() -> None:
    """An empty file yields a clear 'empty' message instead of a cryptic one."""
    with pytest.raises(ConfigError, match="empty or contains no YAML mapping"):
        parse_config_yaml("")


def test_comment_only_file_friendly_error() -> None:
    """A comment-only file behaves like an empty one."""
    with pytest.raises(ConfigError, match="empty or contains no YAML mapping"):
        parse_config_yaml("# nothing here\n")


def test_non_mapping_root_rejected() -> None:
    """A list/scalar root is rejected with a message naming the offending type."""
    with pytest.raises(ConfigError, match="Config root must be a mapping.*got list"):
        parse_config_yaml("- a\n- b\n")


def test_tab_indentation_reports_syntax_error() -> None:
    """Tab indentation surfaces as a YAML syntax error (fail-fast)."""
    content = "version: 1\nproviders:\n\tp:\n\t\tprotocol: openai\n"
    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        parse_config_yaml(content)


def test_merge_keys_allowed_and_resolved() -> None:
    """Anchors + merge keys are standard YAML and resolve safely (allowed, discouraged in docs)."""
    content = """version: 1
providers:
  p1: &base
    protocol: openai
    base_url: http://localhost
    api_key: k
  p2:
    <<: *base
    base_url: http://other:8080
models:
  m:
    provider: p2
    id: m
profiles:
  d2:
    main: m
"""
    cfg = parse_config_yaml(content)
    assert cfg.providers["p1"].base_url == "http://localhost"
    assert cfg.providers["p2"].base_url == "http://other:8080"


def test_dotted_and_slashed_model_keys_preserved() -> None:
    """Model alias keys keep dots/slashes verbatim — they are plain string keys."""
    yaml_str = """version: 1
providers:
  p:
    protocol: openai
    base_url: http://localhost
    api_key: k
models:
  gpt-4o.2:
    provider: p
    id: real-id
  anthropic/claude-3.5:
    provider: p
    id: real-id-2
profiles:
  d:
    pool:
      fast: gpt-4o.2
      sonnet: anthropic/claude-3.5
"""
    cfg = parse_config_yaml(yaml_str)
    assert "gpt-4o.2" in cfg.models
    assert "anthropic/claude-3.5" in cfg.models
