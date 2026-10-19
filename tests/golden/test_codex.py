import json
import tomllib

import pytest
from golden_helpers import manifest_config, plan_of_target, project, seed, target_of

from acm.adapters.base import LaunchContext
from acm.adapters.codex import Codex, catalog_entry, toml_literal
from acm.core.context import Ctx
from acm.engine.model import OwnedFile, Set

pytestmark = pytest.mark.golden
AD = Codex()
PROFILE = '{default: "vmr@default", roles: {review: "vmr@review", subagent: "vmr@subagent", fast: "vmr@fast"}}'


@pytest.fixture
def yctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "VMR_KEY": "sk-gw"}, interactive=False, yes=True)


def cfg_of(ctx):
    return tomllib.loads(next(s.path for s in AD.files(ctx) if s.logical == "config").read_text())


def test_projection_preserves_user_content(yctx):
    seed(yctx, AD, "config", "codex/config.toml")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert project(yctx, AD, t).status == "written"
    c = cfg_of(yctx)
    assert c["model_provider"] == "vmr-responses" and c["model"] == "resp"
    assert c["model_providers"]["vmr-responses"] == {
        "name": "vmr",
        "base_url": "http://gw.test/v1",
        "wire_api": "responses",
        "env_key": "VMR_KEY",
    }
    assert c["review_model"] == "agent" and "default_subagent_model" not in c.get("agents", {})
    assert c["model_catalog_json"].endswith("owned/codex/catalog.json")
    # user content untouched
    assert c["approval_policy"] == "on-request" and c["projects"]["/Users/me/work/app"]
    assert c["mcp_servers"]["docs"]["command"] == "npx" and c["tui"] == {"notifications": True}
    text = next(s.path for s in AD.files(yctx)).read_text()
    assert "# Codex CLI configuration" in text and "sk-gw" not in text


def test_catalog_content(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    plan = plan_of_target(yctx, AD, t)
    cat = next(o for o in plan.ops if isinstance(o, OwnedFile))
    models = json.loads(cat.content)["models"]
    by_slug = {m["slug"]: m for m in models}
    assert set(by_slug) == {"resp", "agent"}  # default, review; fast/subagent are not on Responses
    agent = by_slug["agent"]
    assert agent["display_name"] == "Deep reasoning" and agent["context_window"] == 512000
    assert agent["supported_reasoning_levels"][0]["effort"] == "low"
    assert agent["default_reasoning_level"] == "medium" and agent["input_modalities"] == ["text"]
    assert len(agent["base_instructions"]) > 5000 and agent["visibility"] == "list"
    assert by_slug["resp"]["supported_reasoning_levels"] == []
    assert "context_window" not in by_slug["resp"]  # unknown stays unknown


def test_roles_without_a_slot_warn_and_missing_ones_warn(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    plan = plan_of_target(yctx, AD, t)
    fields = {w.field for w in plan.warnings}
    assert "roles.fast" in fields  # no fast model on Responses
    assert "roles.subagent" in fields  # coding is not on Responses


def test_second_projection_is_noop_and_catalog_drift_is_detected(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    project(yctx, AD, t)
    assert project(yctx, AD, t).status == "noop"
    cat = yctx.acm_home / "owned" / "codex" / "catalog.json"
    cat.write_text("{}")
    res = project(yctx, AD, t)
    assert res.status == "blocked" and "catalog.json" in res.message


def test_literal_key_is_flagged(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-literal"'))
    plan = plan_of_target(yctx, AD, t)
    prov = next(o for o in plan.ops if isinstance(o, Set) and o.path[0] == "model_providers")
    assert prov.value["experimental_bearer_token"] == "sk-literal" and "env_key" not in prov.value
    assert any(w.field == "api_key" for w in plan.warnings)


def test_keyless_gateway_has_no_auth_fields(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='""'))
    prov = next(
        o
        for o in plan_of_target(yctx, AD, t).ops
        if isinstance(o, Set) and o.path[0] == "model_providers"
    )
    assert "env_key" not in prov.value and "experimental_bearer_token" not in prov.value


def test_effort_from_static_card(yctx):
    cfg = """
    version: 4
    providers:
      r:
        protocol: openai-responses
        base_url: https://x/v1
        api_key: "${VMR_KEY}"
        models:
          m: {context_window: 200000, reasoning: true, effort: high, input: [text, image]}
    profiles:
      p: {default: m}
    """
    import textwrap

    t = target_of(yctx, AD, textwrap.dedent(cfg), "p")
    plan = plan_of_target(yctx, AD, t)
    assert any(
        isinstance(o, Set) and o.path == ("model_reasoning_effort",) and o.value == "high"
        for o in plan.ops
    )
    entry = catalog_entry(t.default, 10)
    assert entry["default_reasoning_level"] == "high" and entry["context_window"] == 200000
    assert entry["input_modalities"] == ["text", "image"]


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        (("model",), True),
        (("model_providers", "vmr"), True),
        (("model_providers", "vmr", "base_url"), False),
        (("agents", "default_subagent_model"), True),
        (("agents", "max_threads"), False),
        (("projects",), False),
        (("approval_policy",), False),
    ],
)
def test_whitelist(path, ok):
    assert AD.is_managed("config", path) is ok
    assert AD.is_managed("catalog", path) is False


def test_launch_plan(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    spec = AD.plan_launch(t, yctx, LaunchContext(passthrough=["exec", "hi"], bin_path="/bin/codex"))
    assert (
        spec.mode == "child" and spec.argv[0] == "/bin/codex" and spec.argv[-2:] == ["exec", "hi"]
    )
    pairs = [spec.argv[i + 1] for i, a in enumerate(spec.argv) if a == "-c"]
    assert 'model="resp"' in pairs and 'review_model="agent"' in pairs
    assert any(
        p.startswith("model_providers.vmr-responses={") and 'env_key = "VMR_KEY"' in p
        for p in pairs
    )
    assert 'model_catalog_json="@@RUN_DIR@@/catalog.json"' in pairs
    assert "sk-gw" not in " ".join(spec.argv) and "catalog.json" in spec.tmp_files


def test_launch_with_literal_key_uses_private_env(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-literal"'))
    spec = AD.plan_launch(t, yctx, LaunchContext())
    assert spec.env == {"ACM_RUN_KEY": "sk-literal"} and "sk-literal" not in " ".join(spec.argv)
    assert any('env_key = "ACM_RUN_KEY"' in a for a in spec.argv)


def test_toml_literal_rendering():
    assert toml_literal("a") == '"a"' and toml_literal(3) == "3" and toml_literal(True) == "true"
    assert toml_literal({"a": "x", "n": {"b": 1}}) == '{a = "x", n = {b = 1}}'
    assert toml_literal(["a", "b"]) == '["a", "b"]'
