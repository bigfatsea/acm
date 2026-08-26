# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for VMR probing and proposal generation (WP5a)."""

import http.server
import json
import threading
from pathlib import Path

from conftest import make_vmr_handler

from acm.config import parse_config_yaml
from acm.vmr import (
    VmrModelInfo,
    VmrProbeOutcome,
    VmrProbeResult,
    generate_template_config,
    generate_vmr_proposal,
    probe_vmr,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vmr"


def _start_server(
    models_payload: dict | None = None,
    api_keys: frozenset[str] = frozenset(),
    received_auth_headers: list[str] | None = None,
) -> tuple[http.server.HTTPServer, str]:
    handler = make_vmr_handler(
        models_payload=models_payload,
        api_keys=api_keys,
        received_auth_headers=received_auth_headers,
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, f"http://127.0.0.1:{port}"


def test_probe_vmr_live_server() -> None:
    """Test probe_vmr with a mock running VMR HTTP server."""
    server, url = _start_server()
    try:
        result = probe_vmr({"ACM_VMR_PROBE_URL": url})
        assert result is not None
        assert result.detected is True
        assert result.outcome == VmrProbeOutcome.OK
        assert len(result.models) == 2
        assert result.models[0].id == "coding"
    finally:
        server.shutdown()


def test_probe_vmr_not_running() -> None:
    """Test probe_vmr returns None when no server is running at port."""
    env = {"ACM_VMR_PROBE_URL": "http://127.0.0.1:59999"}
    result = probe_vmr(env)
    assert result is None


def test_probe_auth_required_no_key() -> None:
    """VMR gated with api_keys, no credential offered -> AUTH_REQUIRED, detected=False."""
    server, url = _start_server(api_keys=frozenset({"sk-real"}))
    try:
        result = probe_vmr({"ACM_VMR_PROBE_URL": url})
        assert result is not None
        assert result.detected is False
        assert result.outcome == VmrProbeOutcome.AUTH_REQUIRED
        assert result.models == []
    finally:
        server.shutdown()


def test_probe_auth_required_with_key_succeeds() -> None:
    """Correct VMR_KEY lets the probe enumerate models normally."""
    server, url = _start_server(api_keys=frozenset({"sk-real"}))
    try:
        result = probe_vmr({"ACM_VMR_PROBE_URL": url, "VMR_KEY": "sk-real"})
        assert result is not None
        assert result.detected is True
        assert result.outcome == VmrProbeOutcome.OK
        assert len(result.models) == 2
    finally:
        server.shutdown()


def test_probe_models_down_health_alive_is_degraded() -> None:
    """/v1/models unreachable for a non-auth reason but /health 200 -> DEGRADED."""
    # A server that only answers /health (everything else -> connection reset
    # is hard to simulate cleanly with http.server; instead point /v1/models
    # probing at a closed port on the same probe URL is not possible since
    # both endpoints share one host. Simulate via a handler whose /v1/models
    # 500s, which the probe treats as a non-auth failure.
    class FlakyModelsHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/v1/models":
                self.send_response(500)
                self.end_headers()
            elif self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok","time":"2026-08-26T00:00:00Z","uptime_seconds":1}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FlakyModelsHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        result = probe_vmr({"ACM_VMR_PROBE_URL": f"http://127.0.0.1:{port}"})
        assert result is not None
        assert result.detected is True
        assert result.outcome == VmrProbeOutcome.DEGRADED
        assert result.models == []
    finally:
        server.shutdown()


def test_probe_all_dead_returns_none() -> None:
    """Both /v1/models and /health unreachable -> None (regression protection)."""
    env = {"ACM_VMR_PROBE_URL": "http://127.0.0.1:59999"}
    result = probe_vmr(env)
    assert result is None


def test_probe_never_leaks_key() -> None:
    """The credential is sent only as a request header, never surfaced elsewhere.

    Positive half: the mock server must actually receive it (proves the
    header is sent, not merely "absent from the result" -- which would be
    true even if the header were never sent at all). Negative half: the
    returned result object never carries it.
    """
    received: list[str] = []
    server, url = _start_server(api_keys=frozenset({"sk-super-secret"}), received_auth_headers=received)
    try:
        env = {"ACM_VMR_PROBE_URL": url, "VMR_KEY": "sk-super-secret"}
        result = probe_vmr(env)
        assert result is not None
        assert received == ["Bearer sk-super-secret"]
        assert "sk-super-secret" not in repr(result)
        assert "sk-super-secret" not in str(result.model_dump())
    finally:
        server.shutdown()


def test_probe_ok_with_real_fixture_shape() -> None:
    """Parses a real captured /v1/models response (models_response.golden.json)
    unmodified -- pins the actual VMR wire contract, independent of any
    hand-written test payload, so an upstream shape change shows as a fixture
    diff rather than only a code-review-time reading of conftest.py."""
    fixture = json.loads((FIXTURES_DIR / "models_response.golden.json").read_text())
    server, url = _start_server(models_payload=fixture)
    try:
        result = probe_vmr({"ACM_VMR_PROBE_URL": url})
        assert result is not None
        assert result.outcome == VmrProbeOutcome.OK
        assert [m.id for m in result.models] == ["agent", "cheap", "coding"]
        assert all(m.vmr_protocol == "openai" for m in result.models)
    finally:
        server.shutdown()


def test_generate_vmr_proposal_from_real_fixture_shape() -> None:
    """The real fixture's models round-trip through generate_vmr_proposal into
    a valid CoreConfig, with 'coding' selected as main per the real model set."""
    fixture = json.loads((FIXTURES_DIR / "models_response.golden.json").read_text())
    probe = VmrProbeResult(
        detected=True,
        base_url="http://192.168.0.22:8800/v1",
        models=[VmrModelInfo(id=m["id"], vmr_protocol=m["vmr_protocol"]) for m in fixture["data"]],
    )
    proposal = generate_vmr_proposal(probe)
    cfg = parse_config_yaml(proposal)
    assert {"agent", "cheap", "coding"} <= set(cfg.models)
    assert cfg.profiles["daily"].main == "coding"
    assert cfg.profiles["daily"].cheap == "cheap"


def test_generate_vmr_proposal_is_valid_yaml() -> None:
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
    cfg = parse_config_yaml(proposal)
    assert cfg.version == 1
    assert "vmr" in cfg.providers
    assert "coding" in cfg.models
    assert "cheap" in cfg.models
    assert "daily" in cfg.profiles
    assert cfg.profiles["daily"].main == "coding"
    assert cfg.profiles["daily"].cheap == "cheap"


def test_generate_template_config_is_valid_yaml() -> None:
    """Test default template configuration parses cleanly into CoreConfig."""
    template = generate_template_config()
    cfg = parse_config_yaml(template)
    assert cfg.version == 1
    assert "anthropic-direct" in cfg.providers
    assert "daily" in cfg.profiles


def test_generate_vmr_proposal_with_dotted_and_namespaced_model_ids() -> None:
    """Generated proposal keeps dotted/slashes/colon model ids verbatim as alias keys."""
    probe = VmrProbeResult(
        detected=True,
        base_url="http://127.0.0.1:8800/v1",
        models=[
            VmrModelInfo(id="gpt-4.1-mini", vmr_protocol="openai"),
            VmrModelInfo(id="anthropic/claude-3.7-sonnet:thinking", vmr_protocol="openai"),
        ],
    )
    proposal = generate_vmr_proposal(probe)
    cfg = parse_config_yaml(proposal)
    assert cfg.version == 1
    # YAML mapping keys are plain strings: ids stay verbatim (no sanitization).
    assert "gpt-4.1-mini" in cfg.models
    assert "anthropic/claude-3.7-sonnet:thinking" in cfg.models
