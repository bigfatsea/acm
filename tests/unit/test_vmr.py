# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for VMR probing and proposal generation (WP5a)."""

import http.server
import json
import threading
from typing import Any

from acm.config import parse_config_toml
from acm.vmr import (
    VmrModelInfo,
    VmrProbeResult,
    generate_template_config,
    generate_vmr_proposal,
    probe_vmr,
)


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


def test_probe_vmr_live_server() -> None:
    """Test probe_vmr with a mock running VMR HTTP server."""
    server = http.server.HTTPServer(("127.0.0.1", 0), MockVmrHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        env = {"ACM_VMR_PROBE_URL": f"http://127.0.0.1:{port}"}
        result = probe_vmr(env)
        assert result is not None
        assert result.detected is True
        assert len(result.models) == 2
        assert result.models[0].id == "coding"
    finally:
        server.shutdown()


def test_probe_vmr_not_running() -> None:
    """Test probe_vmr returns None when no server is running at port."""
    env = {"ACM_VMR_PROBE_URL": "http://127.0.0.1:59999"}
    result = probe_vmr(env)
    assert result is None


def test_generate_vmr_proposal_is_valid_toml() -> None:
    """Test generated VMR proposal parses cleanly into CoreConfig."""
    probe = VmrProbeResult(
        detected=True,
        base_url="http://127.0.0.1:8800/v1",
        models=[
            VmrModelInfo(id="coding", vmr_protocol="openai"),
            VmrModelInfo(id="cheap", vmr_protocol="openai"),
        ],
    )
    proposal = generate_vmr_proposal(probe)
    cfg = parse_config_toml(proposal)
    assert cfg.version == 1
    assert "vmr" in cfg.providers
    assert "coding" in cfg.models
    assert "cheap" in cfg.models
    assert "daily" in cfg.profiles
    assert cfg.profiles["daily"].main == "coding"
    assert cfg.profiles["daily"].cheap == "cheap"


def test_generate_template_config_is_valid_toml() -> None:
    """Test default template configuration parses cleanly into CoreConfig."""
    template = generate_template_config()
    cfg = parse_config_toml(template)
    assert cfg.version == 1
    assert "anthropic-direct" in cfg.providers
    assert "daily" in cfg.profiles


def test_generate_vmr_proposal_with_dotted_and_namespaced_model_ids() -> None:
    """Test generated VMR proposal with dotted model names like gpt-4.1-mini parses into CoreConfig."""
    probe = VmrProbeResult(
        detected=True,
        base_url="http://127.0.0.1:8800/v1",
        models=[
            VmrModelInfo(id="gpt-4.1-mini", vmr_protocol="openai"),
            VmrModelInfo(id="anthropic/claude-3.7-sonnet:thinking", vmr_protocol="openai"),
        ],
    )
    proposal = generate_vmr_proposal(probe)
    cfg = parse_config_toml(proposal)
    assert cfg.version == 1
    assert "gpt-4.1-mini" in cfg.models
    assert "anthropic-claude-3.7-sonnet-thinking" in cfg.models
