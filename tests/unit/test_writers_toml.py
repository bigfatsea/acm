# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for TOML round-trip editor (WP2)."""

from acm.writers.json_editor import NOT_FOUND
from acm.writers.toml_editor import delete_toml_path, read_toml_path, set_toml_path


def test_read_toml_path() -> None:
    """Test reading values from TOML string."""
    toml = """# Top header comment
model = "gpt-4o"
model_reasoning_effort = "medium"

[features]
auto_compact = true

[model_providers.coding]
base_url = "http://localhost:8800/v1"
wire_api = "openai"
"""
    assert read_toml_path(toml, "model") == "gpt-4o"
    assert read_toml_path(toml, "model_reasoning_effort") == "medium"
    assert read_toml_path(toml, "features.auto_compact") is True
    assert read_toml_path(toml, "model_providers.coding.base_url") == "http://localhost:8800/v1"
    assert read_toml_path(toml, "non_existent") is NOT_FOUND


def test_set_toml_path_preserves_comments_and_tables() -> None:
    """Test setting values in TOML preserves comments and unmanaged tables."""
    toml = """# Unmanaged top-level comment
model = "old-model" # Inline comment

# Important MCP servers configuration
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem"]

[features]
sandbox = "workspace"
"""
    updated = set_toml_path(toml, "model", "new-coding-model")
    updated = set_toml_path(updated, "model_providers.coding.base_url", "http://127.0.0.1:8800/v1")
    updated = set_toml_path(updated, "model_providers.coding.wire_api", "openai")

    assert "# Unmanaged top-level comment" in updated
    assert "# Important MCP servers configuration" in updated
    assert read_toml_path(updated, "model") == "new-coding-model"
    assert read_toml_path(updated, "mcp_servers.filesystem.command") == "npx"
    assert read_toml_path(updated, "features.sandbox") == "workspace"
    assert read_toml_path(updated, "model_providers.coding.base_url") == "http://127.0.0.1:8800/v1"


def test_delete_toml_path() -> None:
    """Test deleting keys in TOML."""
    toml = """[a]
b = 1
c = 2
"""
    updated = delete_toml_path(toml, "a.b")
    assert read_toml_path(updated, "a.b") is NOT_FOUND
    assert read_toml_path(updated, "a.c") == 2
