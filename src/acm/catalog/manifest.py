"""Manifest v1: schema, fetching with ETag + cache, conversion to a runtime Provider."""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from acm import __version__
from acm.catalog.model import PROTOCOL_ORDER, ModelCard, Provider
from acm.config.refs import ROLES, CredentialRef, parse_credential
from acm.core.context import Ctx
from acm.core.errors import ConfigError, IOFailureError
from acm.engine.history import now_iso

DEFAULT_TIMEOUT = 2.0


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Gateway(_Lenient):
    kind: str = "gateway"
    version: str | None = None
    name: str | None = None


class Limit(_Lenient):
    context: int | None = None
    context_floor: int | None = None
    output: int | None = None


class Modalities(_Lenient):
    input: list[str] = Field(default_factory=lambda: ["text"])


class ManifestModel(_Lenient):
    id: str
    display_name: str | None = None
    description: str | None = None
    protocols: list[str]
    roles: list[str] = Field(default_factory=list)
    limit: Limit | None = None
    modalities: Modalities | None = None
    tool_call: bool | None = None
    reasoning: bool | None = None


class Manifest(_Lenient):
    manifest_version: int
    gateway: Gateway = Field(default_factory=Gateway)
    endpoints: dict[str, str]
    models: list[ManifestModel]


def parse_manifest(data: Any, source: str = "manifest") -> Manifest:
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: the manifest must be a JSON object")
    version = data.get("manifest_version")
    if version != 1:
        raise ConfigError(
            f"{source}: unsupported manifest_version {version!r} (this acm understands 1); "
            "upgrade acm or the gateway"
        )
    try:
        m = Manifest.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        raise ConfigError(f"{source}: invalid manifest at {loc}: {first['msg']}") from e
    return m


def manifest_to_cards(provider: str, m: Manifest, source: str) -> tuple[ModelCard, ...]:
    cards: list[ModelCard] = []
    claimed: dict[tuple[str, str], str] = {}
    for mm in m.models:
        protos = tuple(p for p in PROTOCOL_ORDER if p in mm.protocols and p in m.endpoints)
        if not protos:
            continue  # only protocols this acm (or this gateway's endpoints) does not know
        roles = tuple(r for r in mm.roles if r in ROLES)
        for p in protos:
            for r in roles:
                if (p, r) in claimed:
                    raise ConfigError(
                        f"{source}: invalid manifest: role '{r}' on {p} is claimed by both "
                        f"'{claimed[(p, r)]}' and '{mm.id}'"
                    )
                claimed[(p, r)] = mm.id
        lim = mm.limit or Limit()
        cards.append(
            ModelCard(
                provider=provider,
                id=mm.id,
                protocols=protos,
                roles=roles,
                display_name=mm.display_name,
                description=mm.description,
                context=lim.context,
                context_floor=lim.context_floor,
                output=lim.output,
                input=tuple(mm.modalities.input) if mm.modalities else ("text",),
                tool_call=mm.tool_call,
                reasoning=mm.reasoning,
            )
        )
    return tuple(cards)


def provider_from_manifest(
    name: str,
    m: Manifest,
    *,
    credential: CredentialRef,
    headers: Mapping[str, str],
    source: str,
    note: str | None = None,
) -> Provider:
    endpoints = {p: m.endpoints[p].rstrip("/") for p in PROTOCOL_ORDER if p in m.endpoints}
    if not endpoints:
        raise ConfigError(f"{source}: the manifest declares no usable endpoints")
    return Provider(
        name=name,
        endpoints=endpoints,
        credential=credential,
        cards=manifest_to_cards(name, m, source),
        headers=dict(headers),
        origin="manifest",
        source=source,
        note=note,
    )


# ------------------------------------------------------------------ fetching


@dataclass
class Fetched:
    data: dict[str, Any]
    note: str | None = None


def _timeout(ctx: Ctx) -> float:
    try:
        return float(ctx.env.get("ACM_MANIFEST_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def resolve_source(ctx: Ctx, raw: str) -> str:
    """Expand a ``${VAR}`` manifest reference; returns a URL or an absolute file path string."""
    cred = parse_credential(raw)
    text = cred.resolve(ctx.env) if cred.is_reference else raw
    if text.startswith("file://"):
        return str(Path(unquote(urlparse(text).path)))
    if text.startswith(("http://", "https://")):
        return text
    p = ctx.expand(text)
    return str(p if p.is_absolute() else Path.cwd() / p)


def _cache_path(ctx: Ctx, provider: str) -> Path:
    return ctx.manifests_dir / f"{provider}.json"


def _read_cache(ctx: Ctx, provider: str, url: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(_cache_path(ctx, provider).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(obj, dict) and obj.get("url") == url and isinstance(obj.get("body"), dict):
        return obj
    return None


def _write_cache(ctx: Ctx, provider: str, url: str, etag: str | None, body: dict[str, Any]) -> None:
    p = _cache_path(ctx, provider)
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = p.with_name(f".{p.name}.acm_tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"url": url, "etag": etag, "fetched_at": now_iso(), "body": body}, f)
        os.replace(tmp, p)
    except OSError:
        pass  # a cache that cannot be written only costs offline resilience


def _age(iso: str | None) -> str:
    try:
        secs = (datetime.now().astimezone() - datetime.fromisoformat(str(iso))).total_seconds()
    except (TypeError, ValueError):
        return "at an unknown time"
    if secs < 90:
        return "moments ago"
    if secs < 5400:
        return f"{round(secs / 60)} min ago"
    if secs < 172800:
        return f"{round(secs / 3600)} h ago"
    return f"{round(secs / 86400)} d ago"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the credential to another host: treat it as a failure."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect)


def fetch_manifest(
    ctx: Ctx, provider: str, source: str, api_key: str, headers: Mapping[str, str]
) -> Fetched:
    """Return the manifest document, honouring the failure matrix of SPEC §4.3."""
    if not source.startswith(("http://", "https://")):
        try:
            return Fetched(json.loads(Path(source).read_text(encoding="utf-8")))
        except OSError as e:
            raise IOFailureError(f"cannot read manifest file {source}: {e}") from e
        except ValueError as e:
            raise ConfigError(f"{source}: not valid JSON: {e}") from e
    cached = _read_cache(ctx, provider, source)
    req_headers = {
        "Accept": "application/json",
        "User-Agent": f"acm/{__version__}",
        **dict(headers),
    }
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"
    if cached and cached.get("etag"):
        req_headers["If-None-Match"] = str(cached["etag"])
    req = urllib.request.Request(source, headers=req_headers)
    try:
        with _opener().open(req, timeout=_timeout(ctx)) as resp:
            raw = resp.read()
            etag = resp.headers.get("ETag")
        try:
            body = json.loads(raw)
        except ValueError as e:
            raise ConfigError(f"{source}: response is not valid JSON") from e
        if not isinstance(body, dict):
            raise ConfigError(f"{source}: response is not a JSON object")
        parse_manifest(body, source)  # never cache a document that cannot be used
        _write_cache(ctx, provider, source, etag, body)
        return Fetched(body)
    except urllib.error.HTTPError as e:
        if e.code == 304 and cached:
            return Fetched(cached["body"])
        if e.code in (401, 403):
            raise ConfigError(
                f"{source}: the gateway refused the credential (HTTP {e.code}); "
                "check the provider's api_key / environment variable"
            ) from e
        if e.code == 404:
            raise ConfigError(
                f"{source}: no manifest there (HTTP 404) - does the gateway publish /manifest?"
            ) from e
        err = f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        err = str(getattr(e, "reason", e))
    if cached:
        return Fetched(
            cached["body"],
            note=(
                f"manifest for '{provider}' served from cache (fetched "
                f"{_age(cached.get('fetched_at'))}); gateway unreachable: {err}"
            ),
        )
    raise IOFailureError(f"cannot reach {source} and no cached manifest exists: {err}")


def load_manifest_provider(
    ctx: Ctx,
    name: str,
    raw_source: str,
    credential: CredentialRef,
    headers: Mapping[str, str],
) -> Provider:
    source = resolve_source(ctx, raw_source)
    key = credential.try_resolve(ctx.env) or ""
    fetched = fetch_manifest(ctx, name, source, key, headers)
    m = parse_manifest(fetched.data, source)
    return provider_from_manifest(
        name, m, credential=credential, headers=headers, source=source, note=fetched.note
    )
