# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Pytest test configuration and fixtures."""

import http.server
import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from acm.adapters import PlannedOp, ProjectionWarning
from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider


class MockVmrHandler(http.server.BaseHTTPRequestHandler):
    """Mock HTTP handler simulating VMR endpoints."""

    def do_GET(self) -> None:
        if self.path == "/v1/models":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "data": [
                    {"id": "coding", "vmr_protocol": "openai"},
                    {"id": "cheap", "vmr_protocol": "openai"},
                ]
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        elif self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Quiet during tests


@pytest.fixture(autouse=True)
def isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate HOME and XDG directories to tmp_path for all tests."""
    from acm.adapters import clear_adapters

    clear_adapters()
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / ".config"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    # Guarantee offline VMR dead port by default so tests never hit live host ports
    monkeypatch.setenv("ACM_VMR_PROBE_URL", "http://127.0.0.1:9")
    return fake_home


@pytest.fixture
def fake_vmr_server(monkeypatch: pytest.MonkeyPatch) -> str:
    """Fixture providing a mock live VMR server with standard models (coding, cheap)."""
    server = http.server.HTTPServer(("127.0.0.1", 0), MockVmrHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("ACM_VMR_PROBE_URL", url)
    return url


@pytest.fixture
def tmp_home(isolate_home: Path) -> Path:
    """Fixture providing isolated home directory."""
    return isolate_home


@pytest.fixture
def make_config(tmp_home: Path) -> Callable[[str], Path]:
    """Helper to create a ~/.acm/config.yaml file with custom content."""

    def _maker(content: str) -> Path:
        acm_dir = tmp_home / ".acm"
        acm_dir.mkdir(parents=True, exist_ok=True)
        config_path = acm_dir / "config.yaml"
        config_path.write_text(content, encoding="utf-8")
        return config_path

    return _maker


@pytest.fixture
def sample_config_yaml() -> str:
    """Return a standard valid config.yaml string."""
    return """version: 1

providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY:-sk-test-mock-key}"

  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY:-sk-ant-test-key}"

models:
  coding:
    provider: vmr
    id: coding
    context_window: 131072
    max_output_tokens: 16384
    temperature: 0.2
    reasoning:
      effort: high
      budget_tokens: 16000

  claude-sonnet:
    provider: anthropic-direct
    id: claude-3-7-sonnet-20250219

profiles:
  daily:
    main: coding

  direct:
    main: claude-sonnet
"""


@pytest.fixture
def env_override(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Helper to set environment variables."""

    def _override(**kwargs: str) -> None:
        for k, v in kwargs.items():
            monkeypatch.setenv(k, v)

    return _override


class MockAdapter:
    """Stub adapter for testing."""

    AGENT_ID = "mock_agent"
    DISPLAY_NAME = "Mock Agent"

    def __init__(self, target_file: Path, detected: bool = True) -> None:
        self.target_file = target_file
        self.is_detected = detected

    def detect(self, env: Mapping[str, str] | None = None) -> bool:
        return self.is_detected

    def config_paths(self, env: Mapping[str, str] | None = None) -> list[Path]:
        return [self.target_file]

    def managed_namespaces(self) -> list[str]:
        return ["model", "env.KEY"]

    def plan(
        self, profile: ResolvedProfile, env: Mapping[str, str] | None = None
    ) -> tuple[list[PlannedOp], list[ProjectionWarning]]:
        return (
            [PlannedOp(file=self.target_file, path="model", new=profile.main.upstream_id)],
            [],
        )


def make_mock_profile(model_id: str = "coding") -> ResolvedProfile:
    """Helper to create a minimal ResolvedProfile."""
    provider = ResolvedProvider(
        name="mock_p",
        protocol="openai",
        base_url="http://localhost:8800",
        api_key="mock_key",
        raw_api_key_ref="${KEY}",
    )
    model = ResolvedModel(
        model_id="coding",
        upstream_id=model_id,
        provider=provider,
    )
    return ResolvedProfile(profile_name="daily", main=model)
