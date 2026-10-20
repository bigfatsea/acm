"""Generate the ``config.yaml`` proposal shown by ``acm init``."""

import json
import re

from acm.catalog.manifest import parse_manifest
from acm.catalog.probe import ProbeResult
from acm.config.refs import NON_DEFAULT_ROLES


def _q(value: str) -> str:
    return json.dumps(value)  # JSON strings are valid YAML double-quoted scalars


def provider_name(kind: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", kind).strip("-")
    return name or "gateway"


def proposal_for(probe: ProbeResult, *, key_var: str = "VMR_KEY") -> str:
    if probe.outcome == "manifest":
        return _manifest_proposal(probe, key_var)
    if probe.outcome == "models":
        return _models_proposal(probe, key_var)
    return template_config()


def _manifest_proposal(probe: ProbeResult, key_var: str) -> str:
    assert probe.manifest is not None
    m = parse_manifest(probe.manifest)
    name = provider_name(m.gateway.kind)
    roles: dict[str, str] = {}
    for model in m.models:
        for r in model.roles:
            roles.setdefault(r, model.id)
    default_ref = f"{name}@default" if "default" in roles else f"{name}.{m.models[0].id}"
    auth = probe.manifest.get("auth")
    keyless = isinstance(auth, dict) and auth.get("required") is False
    lines = [
        "version: 4",
        "",
        f"# The gateway publishes its model catalog at {probe.base_url}/manifest; acm resolves it",
        "# each time it projects, so the catalog is never copied into this file.",
        "providers:",
        f"  {name}:",
        f"    manifest: {_q(probe.base_url + '/manifest')}",
    ]
    if keyless:  # the gateway takes no key today; an unset variable must not stop acm
        lines.append(f'    api_key: "${{{key_var}:-}}"   # the gateway requires no key')
    else:
        lines.append(f'    api_key: "${{{key_var}}}"')
    lines += ["", "profiles:", "  daily:"]
    if not roles:
        ids = ", ".join(mm.id for mm in m.models)
        lines += [
            "    # The gateway tags no model with a role (VMR: models.<name>.meta.roles), so only",
            f"    # a default could be guessed. Pick models by name instead ({ids}):",
            f'    # roles: {{fast: "{name}.<model>", reasoning: "{name}.<model>"}}',
        ]
    lines.append(f"    default: {_q(default_ref)}")
    extra = [r for r in NON_DEFAULT_ROLES if r in roles]
    if extra:
        lines.append("    roles:")
        lines.extend(f"      {r}: {_q(f'{name}@{r}')}" for r in extra)
    return "\n".join(lines) + "\n"


_SUFFIX = {
    "openai-completions": "",
    "anthropic-messages": "-anthropic",
    "openai-responses": "-responses",
}


def _models_proposal(probe: ProbeResult, key_var: str) -> str:
    by_proto: dict[str, list[str]] = {}
    for mid, proto in probe.models:
        by_proto.setdefault(proto, []).append(mid)
    order = [p for p in _SUFFIX if p in by_proto]
    names = {p: "vmr" + _SUFFIX[p] for p in order}
    lines = ["version: 4", "", "providers:"]
    for p in order:
        base = probe.base_url if p == "anthropic-messages" else probe.base_url + "/v1"
        lines += [
            f"  {names[p]}:",
            f"    protocol: {p}",
            f"    base_url: {_q(base)}",
            f'    api_key: "${{{key_var}:-}}"',
            "    models:",
        ]
        lines += [f"      {_q(mid)}: {{}}" for mid in by_proto[p]]
        lines.append("")
    first = order[0]
    ids = by_proto[first]
    default_model = "coding" if "coding" in ids else ids[0]
    lines += ["profiles:", "  daily:", f"    default: {_q(names[first] + '.' + default_model)}"]
    return "\n".join(lines) + "\n"


def template_config() -> str:
    return """version: 4

# Providers: where requests go. Credentials are ${VAR} references - never put keys here.
providers:
  anthropic:
    protocol: anthropic-messages
    base_url: https://api.anthropic.com        # no /v1 for anthropic-messages
    api_key: "${ANTHROPIC_API_KEY}"
    models:
      claude-sonnet-5-5: {context_window: 1000000, roles: [default]}
      claude-haiku-5-5: {roles: [fast]}

  # A gateway that publishes a Manifest (for example VMR) needs only:
  # team:
  #   manifest: "https://vmr.example.com/manifest"
  #   api_key: "${VMR_KEY}"

# Profiles: what you want. `acm use daily` projects it onto every installed agent.
profiles:
  daily:
    default: anthropic.claude-sonnet-5-5
    roles:
      fast: anthropic@fast
"""
