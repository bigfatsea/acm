import json
import textwrap

import pytest
from golden_helpers import manifest_config, plan_of_target, project, seed, target_of

from acm.adapters.base import LaunchContext
from acm.adapters.pi import OMO, PI, PRIME, PiFamily
from acm.core.context import Ctx
from acm.engine.model import Set

pytestmark = pytest.mark.golden
AD = PiFamily(PI)
PROFILE = '{default: "vmr@default", roles: {reasoning: "vmr@reasoning", fast: "vmr@fast", subagent: "vmr@subagent", review: "vmr@review"}, models: {deep: "vmr.agent"}}'
WITH_CLAUDE = '{default: "vmr@default", models: {deep: "vmr.agent", sonnet: "vmr.claude"}}'


@pytest.fixture
def yctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "VMR_KEY": "sk-gw"}, interactive=False, yes=True)


def read(ctx, ad, logical):
    return json.loads(next(s.path for s in ad.files(ctx) if s.logical == logical).read_text())


def test_projection_registers_models_and_keeps_user_providers(yctx):
    seed(yctx, AD, "models", "pi/models.json")
    seed(yctx, AD, "settings", "pi/settings.json")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert project(yctx, AD, t).status == "written"
    models = read(yctx, AD, "models")["providers"]
    assert set(models) == {"ollama", "vmr"}
    assert models["ollama"]["models"] == [{"id": "llama3.1:8b", "contextWindow": 131072}]
    vmr = models["vmr"]
    assert vmr["api"] == "openai-completions" and vmr["baseUrl"] == "http://gw.test/v1"
    assert vmr["apiKey"] == "$VMR_KEY"
    ids = {m["id"]: m for m in vmr["models"]}
    assert set(ids) == {"coding", "agent", "cheap"}
    assert ids["coding"]["contextWindow"] == 200000  # the conservative floor
    assert ids["agent"]["name"] == "deep" and ids["agent"]["reasoning"] is True
    s = read(yctx, AD, "settings")
    assert s["defaultProvider"] == "vmr" and s["defaultModel"] == "coding"
    assert s["theme"] == "dark" and s["enabledModels"] == ["ollama/*"]
    assert "sk-gw" not in json.dumps(models)


def test_a_model_only_available_over_another_protocol_gets_its_own_provider_entry(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, WITH_CLAUDE))
    project(yctx, AD, t)
    models = read(yctx, AD, "models")["providers"]
    assert set(models) == {"vmr", "vmr-anthropic"}
    assert models["vmr-anthropic"]["api"] == "anthropic-messages"
    assert models["vmr-anthropic"]["baseUrl"] == "http://gw.test"
    assert [m["id"] for m in models["vmr-anthropic"]["models"]] == ["claude"]
    assert models["vmr-anthropic"]["models"][0]["name"] == "sonnet"  # the profile label


def test_second_projection_is_noop(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    project(yctx, AD, t)
    assert project(yctx, AD, t).status == "noop"


def test_roles_without_a_slot_warn_but_registered_roles_do_not(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    fields = {w.field for w in plan_of_target(yctx, AD, t).warnings}
    assert {"roles.subagent", "roles.review"} <= fields
    assert "roles.fast" not in fields and "roles.reasoning" not in fields


def test_removed_provider_group_is_retired(yctx):
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, WITH_CLAUDE)))
    assert "vmr-anthropic" in read(yctx, AD, "models")["providers"]
    only_oai = '{default: "vmr@default", roles: {fast: "vmr@fast"}}'
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, only_oai)))
    assert "vmr-anthropic" not in read(yctx, AD, "models")["providers"]


def test_keyless_gets_dummy_and_literal_is_flagged(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='""'))
    objs = [
        o.value
        for o in plan_of_target(yctx, AD, t).ops
        if isinstance(o, Set) and o.file == "models"
    ]
    assert all(o["apiKey"] == "dummy" for o in objs)
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-lit"'))
    plan = plan_of_target(yctx, AD, t)
    assert any(w.field == "api_key" for w in plan.warnings)


def test_effort_becomes_thinking_level(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          r:
            protocol: openai-completions
            base_url: https://x/v1
            api_key: "${VMR_KEY}"
            models:
              m: {effort: high, reasoning: true, input: [text, image], max_output_tokens: 8000}
        profiles:
          p: {default: m}
        """
    )
    t = target_of(yctx, AD, cfg, "p")
    project(yctx, AD, t)
    assert read(yctx, AD, "settings")["defaultThinkingLevel"] == "high"
    m = read(yctx, AD, "models")["providers"]["r"]["models"][0]
    assert m["input"] == ["text", "image"] and m["maxTokens"] == 8000 and m["reasoning"] is True


@pytest.mark.parametrize(
    ("logical", "path", "ok"),
    [
        ("models", ("providers", "vmr"), True),
        ("models", ("providers",), False),
        ("models", ("providers", "vmr", "apiKey"), False),
        ("settings", ("defaultModel",), True),
        ("settings", ("theme",), False),
        ("settings", ("enabledModels",), False),
    ],
)
def test_whitelist(logical, path, ok):
    assert AD.is_managed(logical, path) is ok


def test_family_members_differ_only_by_parameters(yctx, tmp_path):
    for member, rel in ((OMO, ".omo/agent"), (PRIME, ".prime/agent")):
        ad = PiFamily(member)
        assert ad.tier == "T2" and ad.agent_dir(yctx) == yctx.home / rel
        assert [s.logical for s in ad.files(yctx)] == ["models", "settings"]
        project(yctx, ad, target_of(yctx, ad, manifest_config(yctx, PROFILE)))
        assert read(yctx, ad, "settings")["defaultProvider"] == "vmr"
    assert PiFamily(PI).tier == "T1"
    assert PiFamily(OMO).matches("omo-ai") and PiFamily(PRIME).matches("prime")


def test_directory_override_env(ctx, tmp_path):
    d = tmp_path / "elsewhere"
    c = Ctx.from_env({**ctx.env, "OMO_CODING_AGENT_DIR": str(d)}, interactive=False)
    assert PiFamily(OMO).agent_dir(c) == d
    c = Ctx.from_env({**ctx.env, "SENPI_CODING_AGENT_DIR": "~/senpi"}, interactive=False)
    assert PiFamily(OMO).agent_dir(c) == c.home / "senpi"
    c = Ctx.from_env({**ctx.env, "PI_CODING_AGENT_DIR": "relative/dir"}, interactive=False)
    assert PiFamily(PI).agent_dir(c) == c.home / ".pi" / "agent"  # relative paths are ignored


def test_launch_plan(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, WITH_CLAUDE))
    spec = AD.plan_launch(t, yctx, LaunchContext(passthrough=["-p", "hi"], bin_path="/bin/pi"))
    assert spec.argv[:2] == ["/bin/pi", "-e"] and spec.argv[2].endswith("acm_pi_provider.ts")
    assert spec.argv[3:5] == ["--model", "vmr/coding"] and spec.argv[-2:] == ["-p", "hi"]
    providers = json.loads(spec.env["ACM_PI_PROVIDERS"])
    assert {p["alias"] for p in providers} == {"vmr", "vmr-anthropic"}
    assert providers[0]["apiKey"] == "$VMR_KEY" and "sk-gw" not in json.dumps(spec.env)


def test_launch_with_literal_key(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-lit"'))
    spec = AD.plan_launch(t, yctx, LaunchContext())
    assert spec.env["ACM_RUN_KEY"] == "sk-lit" and "sk-lit" not in spec.env["ACM_PI_PROVIDERS"]
    assert all(p["apiKey"] == "$ACM_RUN_KEY" for p in json.loads(spec.env["ACM_PI_PROVIDERS"]))


def test_launch_routes_roles_through_the_auto_virtual_model(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    spec = AD.plan_launch(t, yctx, LaunchContext(bin_path="/bin/pi"))
    assert spec.argv[3:] == ["--model", "acm/auto", "--thinking", "medium"]
    router = json.loads(spec.env["ACM_PI_ROUTER"])
    assert {lvl: (x["provider"], x["model"]) for lvl, x in router["tiers"].items()} == {
        "low": ("vmr", "cheap"),
        "medium": ("vmr", "coding"),
        "high": ("vmr", "agent"),
    }
    assert router["tiers"]["medium"]["context"] == 200000  # the conservative floor
    assert router["contextWindow"] == 200000 and "sk-gw" not in spec.env["ACM_PI_ROUTER"]


def test_launch_without_roles_or_with_an_explicit_model_selects_the_model_itself(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}'))
    spec = AD.plan_launch(t, yctx, LaunchContext())
    assert "ACM_PI_ROUTER" not in spec.env and spec.argv[-2:] == ["--model", "vmr/coding"]
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    spec = AD.plan_launch(t, yctx, LaunchContext(model_override=True))
    assert "ACM_PI_ROUTER" not in spec.env and spec.argv[-2:] == ["--model", "vmr/coding"]
