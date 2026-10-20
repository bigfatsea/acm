"""Profiles that mix providers: keys stay with their own endpoint, single-endpoint agents
never route a foreign model to the default provider."""

import json

import pytest
from golden_helpers import target_of

from acm.adapters.base import LaunchContext
from acm.adapters.claude_code import ClaudeCode
from acm.adapters.codex import Codex
from acm.adapters.openclaw import OpenClaw
from acm.adapters.opencode import OPENCODE, OpenCodeFamily
from acm.adapters.pi import PiFamily
from acm.engine.model import Delete, Set

pytestmark = pytest.mark.golden


def _cfg(protocol: str) -> str:
    v1 = "/v1" if protocol.startswith("openai") else ""
    return f"""
version: 4
providers:
  vmr:
    protocol: {protocol}
    base_url: http://vmr.lan{v1}
    api_key: sk-vmr-secret
    models: {{coding: {{}}}}
  ds:
    protocol: {protocol}
    base_url: https://api.deepseek.example{v1}
    api_key: sk-ds-secret
    models: {{cheap: {{}}}}
profiles:
  team:
    default: vmr.coding
    roles: {{fast: ds.cheap, review: ds.cheap, subagent: ds.cheap}}
"""


def test_opencode_run_gives_each_provider_its_own_key(ctx):
    t = target_of(ctx, OpenCodeFamily(OPENCODE), _cfg("openai-completions"))
    spec = OpenCodeFamily(OPENCODE).plan_launch(t, ctx, LaunchContext())
    inline = json.loads(spec.env["OPENCODE_CONFIG_CONTENT"])
    assert inline["provider"]["vmr"]["options"]["apiKey"] == "{env:ACM_RUN_KEY}"
    assert inline["provider"]["ds"]["options"]["apiKey"] == "{env:ACM_RUN_KEY_DS}"
    assert spec.env["ACM_RUN_KEY"] == "sk-vmr-secret"
    assert spec.env["ACM_RUN_KEY_DS"] == "sk-ds-secret"
    assert spec.secret_env == {"ACM_RUN_KEY", "ACM_RUN_KEY_DS"}
    assert "secret" not in spec.env["OPENCODE_CONFIG_CONTENT"]
    assert not any("plain text" in n for n in spec.notes)


def test_pi_run_gives_each_provider_its_own_key(ctx):
    t = target_of(ctx, PiFamily(), _cfg("openai-completions"))
    spec = PiFamily().plan_launch(t, ctx, LaunchContext())
    keys = {p["alias"]: p["apiKey"] for p in json.loads(spec.env["ACM_PI_PROVIDERS"])}
    assert keys == {"vmr": "$ACM_RUN_KEY", "ds": "$ACM_RUN_KEY_DS"}
    assert spec.env["ACM_RUN_KEY_DS"] == "sk-ds-secret"


def test_openclaw_run_gives_each_provider_its_own_key(ctx):
    t = target_of(ctx, OpenClaw(), _cfg("openai-completions"))
    spec = OpenClaw().plan_launch(t, ctx, LaunchContext())
    override = json.loads(spec.argv[spec.argv.index("--config-override") + 1])
    provs = override["models"]["providers"]
    assert provs["vmr"]["apiKey"] == "${ACM_RUN_KEY}"
    assert provs["ds"]["apiKey"] == "${ACM_RUN_KEY_DS}"
    assert "secret" not in " ".join(spec.argv)


def test_claude_code_keeps_foreign_models_out_of_its_slots(ctx):
    ad = ClaudeCode()
    t = target_of(ctx, ad, _cfg("anthropic-messages"))
    plan = ad.plan_files(t, ctx, None)  # type: ignore[arg-type]
    env = {o.path[1]: o.value for o in plan.ops if isinstance(o, Set) and o.path[0] == "env"}
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "coding"
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in env
    assert any("provider 'ds'" in w.reason for w in plan.warnings)
    spec = ad.plan_launch(t, ctx, LaunchContext())
    assert json.loads(spec.argv[2])["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "coding"


def test_codex_keeps_foreign_models_out(ctx):
    ad = Codex()
    t = target_of(ctx, ad, _cfg("openai-responses"))
    plan = ad.plan_files(t, ctx, None)  # type: ignore[arg-type]
    paths = {o.path: o for o in plan.ops if isinstance(o, (Set, Delete))}
    assert isinstance(paths[("review_model",)], Delete)
    assert isinstance(paths[("agents", "default_subagent_model")], Delete)
    catalog = next(o for o in plan.ops if o.file == "catalog")
    slugs = [m["slug"] for m in json.loads(catalog.content)["models"]]  # type: ignore[union-attr]
    assert slugs == ["coding"]
    assert sum("provider 'ds'" in w.reason for w in plan.warnings) == 2  # review, subagent
