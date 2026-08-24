# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for Core Config parsing and schema validation (WP1)."""

from pathlib import Path

import pytest

from acm.config import CoreConfig, load_config, parse_config_toml
from acm.errors import ConfigError


def test_valid_config_parsing(sample_config_toml: str) -> None:
    """Test parsing a valid complete config.toml."""
    cfg = parse_config_toml(sample_config_toml)
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
    toml = """version = 2
[providers.p]
protocol = "openai"
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "p"
id = "m"
[profiles.d]
main = "m"
"""
    with pytest.raises(ConfigError, match="Unsupported config schema version: 2"):
        parse_config_toml(toml)


def test_missing_protocol() -> None:
    """Test provider missing protocol."""
    toml = """version = 1
[providers.p]
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "p"
id = "m"
[profiles.d]
main = "m"
"""
    with pytest.raises(ConfigError):
        parse_config_toml(toml)


def test_invalid_protocol() -> None:
    """Test provider with unsupported protocol dialect."""
    toml = """version = 1
[providers.p]
protocol = "unsupported-protocol"
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "p"
id = "m"
[profiles.d]
main = "m"
"""
    with pytest.raises(ConfigError):
        parse_config_toml(toml)


def test_invalid_base_url() -> None:
    """Test provider with invalid base_url (no http/https)."""
    toml = """version = 1
[providers.p]
protocol = "openai"
base_url = "ftp://invalid-url"
api_key = "k"
[models.m]
provider = "p"
id = "m"
[profiles.d]
main = "m"
"""
    with pytest.raises(ConfigError, match="base_url must start with http:// or https://"):
        parse_config_toml(toml)


def test_model_missing_provider() -> None:
    """Test model referencing non-existent provider."""
    toml = """version = 1
[providers.p1]
protocol = "openai"
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "non_existent_provider"
id = "m"
[profiles.d]
main = "m"
"""
    with pytest.raises(ConfigError, match="references non-existent provider"):
        parse_config_toml(toml)


def test_profile_missing_main_model() -> None:
    """Test profile referencing non-existent main model."""
    toml = """version = 1
[providers.p]
protocol = "openai"
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "p"
id = "m"
[profiles.d]
main = "non_existent_model"
"""
    with pytest.raises(ConfigError, match="main model 'non_existent_model' is not defined"):
        parse_config_toml(toml)


def test_profile_missing_cheap_model() -> None:
    """Test profile referencing non-existent cheap model."""
    toml = """version = 1
[providers.p]
protocol = "openai"
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "p"
id = "m"
[profiles.d]
main = "m"
cheap = "unknown_cheap"
"""
    with pytest.raises(ConfigError, match="cheap model 'unknown_cheap' is not defined"):
        parse_config_toml(toml)


def test_empty_profiles() -> None:
    """Test config without any profiles."""
    toml = """version = 1
[providers.p]
protocol = "openai"
base_url = "http://localhost"
api_key = "k"
[models.m]
provider = "p"
id = "m"
"""
    with pytest.raises(ConfigError, match="must define at least one profile"):
        parse_config_toml(toml)


def test_load_config_file_not_found(tmp_path: Path) -> None:
    """Test loading non-existent config file."""
    with pytest.raises(ConfigError, match="Config file not found"):
        load_config(tmp_path / "non_existent.toml")


def test_load_config_file_success(tmp_path: Path, sample_config_toml: str) -> None:
    """Test loading config from actual file path."""
    p = tmp_path / "config.toml"
    p.write_text(sample_config_toml, encoding="utf-8")
    cfg = load_config(p)
    assert isinstance(cfg, CoreConfig)
    assert cfg.version == 1
