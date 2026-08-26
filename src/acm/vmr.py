# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""VMR (Virtual Model Router) probe and config proposal generation."""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from acm.util import get_env_map

DEFAULT_VMR_HOST = "http://127.0.0.1:8800"


class VmrModelInfo(BaseModel):
    """Discovered VMR model information."""

    model_config = ConfigDict(extra="ignore")

    id: str
    vmr_protocol: str = "openai"


class VmrProbeOutcome(str, Enum):
    """Fine-grained probe result, beyond plain detected/not-detected."""

    OK = "ok"  # /v1/models 200 with an enumerated model list
    AUTH_REQUIRED = "auth_required"  # /v1/models 401/403 -- VMR is up but gated
    DEGRADED = "degraded"  # /v1/models failed for a non-auth reason; /health 200


class VmrProbeResult(BaseModel):
    """Result of probing local VMR."""

    model_config = ConfigDict(extra="forbid")

    detected: bool
    base_url: str
    models: list[VmrModelInfo] = Field(default_factory=list)
    outcome: VmrProbeOutcome = VmrProbeOutcome.OK


def probe_vmr(env: Mapping[str, str] | None = None) -> VmrProbeResult | None:
    """Probe for a running VMR instance via a two-endpoint fault-tolerant sequence.

    Probe sequence:
    1. GET /v1/models (primary data source & evidence; carries a bearer
       credential when VMR_KEY is set -- the same reference the generated
       proposal uses for the provider's own api_key, so probing and later
       `acm use` projection stay consistent with a single variable). A
       401/403 response is itself proof that VMR is running and gated --
       reported immediately as AUTH_REQUIRED (detected=False, so callers
       don't mistakenly generate a VMR proposal from zero known models).
    2. GET /health (unauthenticated liveness -- VMR's /healthz successor;
       /healthz was permanently removed from VMR's routing table). Only
       consulted when step 1 failed for a non-auth reason: 200 there means
       VMR is up but /v1/models itself is unreachable/broken (DEGRADED).

    Returns VmrProbeResult if any evidence of a live VMR was found, None
    otherwise. Never raises network exceptions.
    """
    env_map = get_env_map(env)
    host = env_map.get("ACM_VMR_PROBE_URL", DEFAULT_VMR_HOST).rstrip("/")
    credential = env_map.get("VMR_KEY")

    # 1. Probe /v1/models
    models_url = f"{host}/v1/models"
    headers = {"User-Agent": "acm/0.1.0"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    try:
        req = urllib.request.Request(models_url, headers=headers)
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                parsed = json.loads(body)
                raw_models: list[dict[str, Any]] = []
                if isinstance(parsed, dict) and "data" in parsed:
                    raw_models = parsed["data"]
                elif isinstance(parsed, list):
                    raw_models = parsed

                models: list[VmrModelInfo] = []
                for m in raw_models:
                    if isinstance(m, dict) and "id" in m:
                        m_id = str(m["id"])
                        proto = str(m.get("vmr_protocol", "openai"))
                        if proto not in ("openai", "anthropic", "openai-responses"):
                            proto = "openai"
                        models.append(VmrModelInfo(id=m_id, vmr_protocol=proto))

                return VmrProbeResult(
                    detected=True,
                    base_url=f"{host}/v1",
                    models=models,
                    outcome=VmrProbeOutcome.OK,
                )
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return VmrProbeResult(
                detected=False,
                base_url=f"{host}/v1",
                models=[],
                outcome=VmrProbeOutcome.AUTH_REQUIRED,
            )
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        pass

    # 2. Probe /health (unauthenticated; only reached when step 1 failed for
    #    a reason other than 401/403)
    health_url = f"{host}/health"
    try:
        req = urllib.request.Request(health_url, headers={"User-Agent": "acm/0.1.0"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                return VmrProbeResult(
                    detected=True,
                    base_url=f"{host}/v1",
                    models=[],
                    outcome=VmrProbeOutcome.DEGRADED,
                )
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    return None


def _q(value: Any) -> str:
    """Render a scalar as a YAML-safe double-quoted string.

    JSON string escaping is a valid subset of YAML double-quoted style,
    so json.dumps covers all edge cases (leading indicators, ': ', unicode).
    """
    return json.dumps(str(value))


def generate_vmr_proposal(probe: VmrProbeResult) -> str:
    """Generate a clean, valid config.yaml tailored to detected VMR models."""
    proto = probe.models[0].vmr_protocol if probe.models else "openai"
    lines = [
        "version: 1\n",
        "# ── L1 供应商：端点与凭据引用 ──────────────────────────",
        "providers:",
        "  vmr:",
        f"    protocol: {_q(proto)}",
        f"    base_url: {_q(probe.base_url)}",
        f"    api_key: {_q('${VMR_KEY:-}')}   # 本地 VMR 无鉴权可留空，如需鉴权可 export VMR_KEY\n",
        "# ── L2 模型：规格、行为与能力 ──────────────────────────",
        "models:",
    ]

    model_names: list[str] = []
    if probe.models:
        for m in probe.models:
            # YAML mapping keys are plain strings: dots and slashes stay as-is.
            lines.append(f"  {_q(m.id)}:")
            lines.append("    provider: vmr")
            lines.append(f"    id: {_q(m.id)}")
            lines.append("")
            model_names.append(m.id)
    else:
        lines.append("  # NOTE: VMR is running but models endpoint could not be enumerated.")
        lines.append("  # Please replace 'coding' with your actual target model ID if different.")
        lines.append(f"  {_q('coding')}:")
        lines.append("    provider: vmr")
        lines.append(f"    id: {_q('coding')}")
        lines.append("")
        model_names.append("coding")

    main_model = "coding" if "coding" in model_names else model_names[0]
    cheap_model = "cheap" if "cheap" in model_names else None

    lines.append("# ── L3 Profile：命名的角色组合 ─────────────────────────")
    lines.append("profiles:")
    lines.append("  daily:")
    lines.append(f"    main: {_q(main_model)}")
    if cheap_model and cheap_model != main_model:
        lines.append(f"    cheap: {_q(cheap_model)}")

    return "\n".join(lines) + "\n"


def generate_template_config() -> str:
    """Generate a comprehensive commented template config.yaml when no VMR is detected."""
    return '''version: 1

# ── L1 供应商：端点与凭据引用 ──────────────────────────
providers:
  anthropic-direct:
    protocol: anthropic          # openai | anthropic | openai-responses
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"   # 整字段引用环境变量，零密钥明文入库

  openai-direct:
    protocol: openai
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"

# ── L2 模型：规格、行为与能力 ──────────────────────────
models:
  claude-sonnet:
    provider: anthropic-direct
    id: claude-3-7-sonnet-20250219
    context_window: 200000
    max_output_tokens: 8192
    temperature: 0.2             # 缺省 = 不写入，用 Agent 默认
    reasoning:
      effort: high               # low | medium | high

  gpt-4o:
    provider: openai-direct
    id: gpt-4o
    context_window: 128000
    max_output_tokens: 4096

# ── L3 Profile：命名的角色组合 ─────────────────────────
profiles:
  daily:
    main: claude-sonnet
    cheap: gpt-4o
'''
