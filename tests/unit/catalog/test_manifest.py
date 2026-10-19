import json
import os

import pytest
from fakes import team_manifest

from acm.catalog.manifest import (
    fetch_manifest,
    load_manifest_provider,
    parse_manifest,
    provider_from_manifest,
    resolve_source,
)
from acm.config.refs import parse_credential
from acm.core.context import Ctx
from acm.core.errors import ConfigError, IOFailureError


def load(ctx, gw, key="${K}", name="team"):
    return load_manifest_provider(ctx, name, gw.url + "/manifest", parse_credential(key), {})


@pytest.fixture
def kctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "K": "sk-test-key"}, interactive=False)


def test_fetch_ok_builds_provider_and_cache(kctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    p = load(kctx, gateway)
    assert p.origin == "manifest" and p.primary_protocol == "openai-completions"
    assert p.endpoints["anthropic-messages"] == gateway.url
    assert p.card("agent").protocols == (
        "openai-completions",
        "anthropic-messages",
        "openai-responses",
    )
    assert p.card("coding").effective_context == 200000
    req = gateway.hits("GET", "/manifest")[0]
    assert req["headers"]["authorization"] == "Bearer sk-test-key"
    cache = json.loads((kctx.manifests_dir / "team.json").read_text())
    assert cache["etag"] == '"v1"' and cache["body"]["manifest_version"] == 1
    assert oct((kctx.manifests_dir / "team.json").stat().st_mode & 0o777) == "0o600"


def test_304_uses_cache(kctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    load(kctx, gateway)
    p = load(kctx, gateway)
    assert p.note is None and p.card("coding")
    assert gateway.hits("GET", "/manifest")[1]["headers"]["if-none-match"] == '"v1"'


def test_network_failure_with_cache_warns_with_age(kctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    load(kctx, gateway)
    gateway.stop()
    p = load(kctx, gateway)
    assert p.note and "served from cache" in p.note and "unreachable" in p.note
    assert p.card("cheap")


def test_network_failure_without_cache_is_io_error(kctx, gateway):
    gateway.stop()
    with pytest.raises(IOFailureError, match="no cached manifest"):
        load(kctx, gateway)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_is_config_error(kctx, gateway, status):
    gateway.manifest = team_manifest(gateway.url)
    gateway.key = "other"
    with pytest.raises(ConfigError, match="refused the credential"):
        load(kctx, gateway)


def test_missing_manifest_endpoint(kctx, gateway):
    gateway.manifest = None
    with pytest.raises(ConfigError, match="publish /manifest"):
        load(kctx, gateway)


def test_server_error_without_cache_is_io_error(kctx, gateway):
    gateway.manifest = team_manifest(gateway.url)
    gateway.manifest_status = 500
    with pytest.raises(IOFailureError):
        load(kctx, gateway)


def test_unknown_version_and_bad_structure():
    with pytest.raises(ConfigError, match="manifest_version 2"):
        parse_manifest({"manifest_version": 2})
    with pytest.raises(ConfigError, match="JSON object"):
        parse_manifest([])
    with pytest.raises(ConfigError, match="invalid manifest at"):
        parse_manifest({"manifest_version": 1, "endpoints": {}, "models": [{"id": "x"}]})


def test_unknown_fields_roles_and_protocols_are_ignored():
    m = team_manifest()
    m["future"] = {"x": 1}
    m["models"][0]["roles"].append("planner")
    m["models"][0]["somethingNew"] = True
    m["models"].append({"id": "g", "protocols": ["gemini"], "roles": []})
    m["endpoints"]["gemini"] = "http://x"
    p = provider_from_manifest(
        "t", parse_manifest(m), credential=parse_credential(""), headers={}, source="s"
    )
    assert p.card("coding").roles == ("default", "subagent")
    assert p.card("g") is None  # only protocols this acm does not know -> skipped


def test_duplicate_role_on_a_protocol_is_invalid():
    m = team_manifest()
    m["models"].append({"id": "dup", "protocols": ["openai-completions"], "roles": ["fast"]})
    with pytest.raises(ConfigError, match="role 'fast' on openai-completions"):
        provider_from_manifest(
            "t", parse_manifest(m), credential=parse_credential(""), headers={}, source="s"
        )


def test_protocol_without_endpoint_is_dropped():
    m = team_manifest()
    del m["endpoints"]["openai-responses"]
    p = provider_from_manifest(
        "t", parse_manifest(m), credential=parse_credential(""), headers={}, source="s"
    )
    assert "openai-responses" not in p.endpoints
    assert p.card("resp") is None and p.card("agent").protocols == (
        "openai-completions",
        "anthropic-messages",
    )


def test_file_sources(ctx, tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps(team_manifest("http://h")))
    for raw in (str(f), f"file://{f}"):
        p = load_manifest_provider(ctx, "t", raw, parse_credential(""), {})
        assert p.endpoints["anthropic-messages"] == "http://h"
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_manifest_provider(ctx, "t", str(bad), parse_credential(""), {})
    with pytest.raises(IOFailureError):
        load_manifest_provider(ctx, "t", str(tmp_path / "nope.json"), parse_credential(""), {})


def test_source_may_be_an_env_reference_and_relative_paths_expand(ctx, tmp_path, monkeypatch):
    c = Ctx.from_env({**ctx.env, "SRC": "~/m.json"}, interactive=False)
    assert resolve_source(c, "${SRC}") == str(c.home / "m.json")
    with pytest.raises(ConfigError, match="SRC2 is not set"):
        resolve_source(c, "${SRC2}")
    monkeypatch.chdir(tmp_path)
    assert resolve_source(c, "rel.json") == str(tmp_path / "rel.json")


def test_redirects_are_not_followed(kctx):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/steal")
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(IOFailureError, match="HTTP 302"):
            fetch_manifest(kctx, "t", f"http://127.0.0.1:{srv.server_address[1]}/manifest", "k", {})
    finally:
        srv.shutdown()
        assert os.path.exists(kctx.home)
