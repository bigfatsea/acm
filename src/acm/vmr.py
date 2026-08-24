# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""VMR (Virtual Model Router) probe and config proposal generation."""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from acm.util import get_env_map, get_home

DEFAULT_VMR_HOST = "http://127.0.0.1:8800"


class VmrModelInfo(BaseModel):
    """Discovered VMR model information."""

    model_config = ConfigDict(extra="ignore")

    id: str
    vmr_protocol: str = "openai"


class VmrProbeResult(BaseModel):
    """Result of probing local VMR."""

    model_config = ConfigDict(extra="forbid")

    detected: bool
    base_url: str
    models: list[VmrModelInfo] = Field(default_factory=list)


def probe_vmr(env: Mapping[str, str] | None = None) -> VmrProbeResult | None:
    """Probe for running VMR instance via multi-endpoint fault-tolerant sequence.

    Probe sequence:
    1. GET /v1/models (primary data source & evidence)
    2. GET /healthz (secondary liveness)
    3. ~/.vmr/ fallback directory check

    Returns VmrProbeResult if detected, None otherwise. Never raises network exceptions.
    """
    env_map = get_env_map(env)
    host = env_map.get("ACM_VMR_PROBE_URL", DEFAULT_VMR_HOST).rstrip("/")

    # 1. Probe /v1/models
    models_url = f"{host}/v1/models"
    try:
        req = urllib.request.Request(models_url, headers={"User-Agent": "acm/0.1.0"})
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
                )
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        pass

    # 2. Probe /healthz
    healthz_url = f"{host}/healthz"
    try:
        req = urllib.request.Request(healthz_url, headers={"User-Agent": "acm/0.1.0"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                return VmrProbeResult(
                    detected=True,
                    base_url=f"{host}/v1",
                    models=[],
                )
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    # 3. Check ~/.vmr configuration directory (optional fallback path)
    vmr_home = get_home(env_map) / ".vmr"
    if vmr_home.exists() and (vmr_home / "config.toml").exists():
        return VmrProbeResult(
            detected=True,
            base_url=f"{host}/v1",
            models=[],
        )

    return None


def generate_vmr_proposal(probe: VmrProbeResult) -> str:
    """Generate a clean, valid config.toml tailored to detected VMR models."""
    proto = probe.models[0].vmr_protocol if probe.models else "openai"
    lines = [
        "version = 1\n",
        "# ── L1 供应商：端点与凭据引用 ──────────────────────────",
        "[providers.vmr]",
        f'protocol = "{proto}"',
        f'base_url = "{probe.base_url}"',
        'api_key = "${VMR_KEY:-}" # 本地 VMR 无鉴权可留空，如需鉴权可 export VMR_KEY\n',
        "# ── L2 模型：规格、行为与能力 ──────────────────────────",
    ]

    model_names: list[str] = []
    if probe.models:
        for m in probe.models:
            safe_name = m.id.replace(":", "-").replace("/", "-")
            header_key = f'"{safe_name}"' if ("." in safe_name or " " in safe_name) else safe_name
            lines.append(f"[models.{header_key}]")
            lines.append('provider = "vmr"')
            lines.append(f'id = "{m.id}"')
            lines.append("")
            model_names.append(safe_name)
    else:
        lines.append("# NOTE: VMR is running but models endpoint could not be enumerated.")
        lines.append("# Please replace 'coding' with your actual target model ID if different.")
        lines.append("[models.coding]")
        lines.append('provider = "vmr"')
        lines.append('id = "coding"')
        lines.append("")
        model_names.append("coding")

    main_model = "coding" if "coding" in model_names else model_names[0]
    cheap_model = "cheap" if "cheap" in model_names else None

    lines.append("# ── L3 Profile：命名的角色组合 ─────────────────────────")
    lines.append("[profiles.daily]")
    lines.append(f'main = "{main_model}"')
    if cheap_model and cheap_model != main_model:
        lines.append(f'cheap = "{cheap_model}"')

    return "\n".join(lines) + "\n"


def generate_template_config() -> str:
    """Generate a comprehensive commented template config.toml when no VMR is detected."""
    return """version = 1

# ── L1 供应商：端点与凭据引用 ──────────────────────────
[providers.anthropic-direct]
protocol = "anthropic"
base_url = "https://api.anthropic.com"
api_key = "${ANTHROPIC_API_KEY}" # 整字段引用环境变量，零密钥明文入库

[providers.openai-direct]
protocol = "openai"
base_url = "https://api.openai.com/v1"
api_key = "${OPENAI_API_KEY}"

# ── L2 模型：规格、行为与能力 ──────────────────────────
[models.claude-sonnet]
provider = "anthropic-direct"
id = "claude-3-7-sonnet-20250219"
context_window = 200000
max_output_tokens = 8192
temperature = 0.2

[models.claude-sonnet.reasoning]
effort = "high"

[models.gpt-4o]
provider = "openai-direct"
id = "gpt-4o"
context_window = 128000
max_output_tokens = 4096

# ── L3 Profile：命名的角色组合 ─────────────────────────
[profiles.daily]
main = "claude-sonnet"
cheap = "gpt-4o"
"""
