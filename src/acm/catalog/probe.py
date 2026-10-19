"""Discover a gateway for ``acm init``: Manifest first, then the plain model list."""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal

from acm import __version__
from acm.catalog.manifest import _opener, _timeout, parse_manifest
from acm.core.context import Ctx
from acm.core.errors import ConfigError

DEFAULT_LOCAL_GATEWAY = "http://127.0.0.1:8800"

# VMR's /v1/models reports each model's ingress protocol under "vmr_protocol"
_LEGACY_PROTOCOLS = {
    "openai": "openai-completions",
    "openai-completions": "openai-completions",
    "anthropic": "anthropic-messages",
    "anthropic-messages": "anthropic-messages",
    "openai-responses": "openai-responses",
}


@dataclass
class ProbeResult:
    outcome: Literal["manifest", "models", "auth_required", "none"]
    base_url: str
    manifest: dict[str, Any] | None = None
    models: list[tuple[str, str]] = field(default_factory=list)  # (id, protocol)
    detail: str = ""


def _get(ctx: Ctx, url: str, key: str) -> tuple[int, bytes]:
    headers = {"Accept": "application/json", "User-Agent": f"acm/{__version__}"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with _opener().open(
            urllib.request.Request(url, headers=headers), timeout=_timeout(ctx)
        ) as r:
            return int(r.status), r.read()
    except urllib.error.HTTPError as e:
        return int(e.code), b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def default_gateway_url(ctx: Ctx) -> str:
    return (
        ctx.env.get("VMR_URL") or ctx.env.get("ACM_VMR_PROBE_URL") or DEFAULT_LOCAL_GATEWAY
    ).rstrip("/")


def probe_gateway(ctx: Ctx, base_url: str, key: str = "") -> ProbeResult:
    base = base_url.rstrip("/")
    status, body = _get(ctx, f"{base}/manifest", key)
    if status == 200:
        try:
            data = json.loads(body)
            parse_manifest(data, f"{base}/manifest")
            return ProbeResult("manifest", base, manifest=data)
        except (ValueError, ConfigError) as e:
            return ProbeResult("none", base, detail=f"/manifest returned an unusable document: {e}")
    if status in (401, 403):
        return ProbeResult("auth_required", base, detail="the gateway requires a credential")
    status, body = _get(ctx, f"{base}/v1/models", key)
    if status in (401, 403):
        return ProbeResult("auth_required", base, detail="the gateway requires a credential")
    if status == 200:
        try:
            data = json.loads(body)
        except ValueError:
            return ProbeResult("none", base, detail="/v1/models did not return JSON")
        rows = data.get("data", []) if isinstance(data, dict) else data
        models = [
            (
                str(m["id"]),
                _LEGACY_PROTOCOLS.get(str(m.get("vmr_protocol", "openai")), "openai-completions"),
            )
            for m in rows
            if isinstance(m, dict) and "id" in m
        ]
        if models:
            return ProbeResult("models", base, models=models)
        return ProbeResult("none", base, detail="/v1/models listed no models")
    return ProbeResult("none", base, detail="no gateway answered")
