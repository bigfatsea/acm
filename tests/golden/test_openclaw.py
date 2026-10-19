import json
import textwrap

import pytest
from golden_helpers import manifest_config, plan_of_target, project, seed, target_of

from acm.adapters.base import LaunchContext
from acm.adapters.openclaw import OpenClaw
from acm.core.context import Ctx
from acm.formats.base import parse

pytestmark = pytest.mark.golden
AD = OpenClaw()
PROFILE = '{default: "vmr@default", roles: {fast: "vmr@fast", reasoning: "vmr@reasoning", subagent: "vmr@subagent"}, models: {sonnet: "vmr.claude"}}'


@pytest.fixture
def yctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "VMR_KEY": "sk-gw"}, interactive=False, yes=True)


def tree(ctx):
    return parse("json5", AD.files(ctx)[0].path.read_bytes()).tree()


def test_projection_preserves_json5_style_and_user_content(yctx):
    path = seed(yctx, AD, "config", "openclaw/openclaw.json5")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert project(yctx, AD, t).status == "written"
    text = path.read_text()
    assert text.startswith("// OpenClaw configuration (JSON5)")
    assert "fallbacks: [" in text and "workspace:" in text  # the user's unquoted keys survive
    c = tree(yctx)
    assert c["agents"]["defaults"]["model"] == {
        "primary": "vmr/coding",
        "fallbacks": ["openai/gpt-5.4"],
    }  # the user's object shape and fallbacks are kept
    assert c["agents"]["defaults"]["utilityModel"] == "vmr/cheap"
    assert c["channels"]["whatsapp"]["allowFrom"] == ["+15555550123"]
    assert c["gateway"]["auth"]["token"] == "${OPENCLAW_GATEWAY_TOKEN}"
    assert c["models"]["mode"] == "merge"
    vmr = c["models"]["providers"]["vmr"]
    assert vmr["baseUrl"] == "http://gw.test/v1" and vmr["api"] == "openai-completions"
    assert vmr["apiKey"] == "${VMR_KEY}"
    ids = {m["id"]: m for m in vmr["models"]}
    assert set(ids) == {"coding", "agent", "cheap"} and ids["coding"]["contextWindow"] == 200000
    assert c["models"]["providers"]["vmr-anthropic"]["api"] == "anthropic-messages"
    assert "sk-gw" not in text


def test_string_model_slot_stays_a_string(yctx):
    p = AD.files(yctx)[0].path
    p.parent.mkdir(parents=True)
    p.write_text(
        '{ agents: { defaults: { model: "anthropic/claude-opus-4-6", utilityModel: "x/y" } } }'
    )
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, PROFILE)))
    d = tree(yctx)["agents"]["defaults"]
    assert d["model"] == "vmr/coding" and d["utilityModel"] == "vmr/cheap"


def test_second_projection_is_noop(yctx):
    seed(yctx, AD, "config", "openclaw/openclaw.json5")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    project(yctx, AD, t)
    assert project(yctx, AD, t).status == "noop"


def test_include_directives_make_the_agent_an_error(yctx):
    p = AD.files(yctx)[0].path
    p.parent.mkdir(parents=True)
    p.write_text('{ agents: { $include: "./agents.json5" } }')
    plan = plan_of_target(yctx, AD, target_of(yctx, AD, manifest_config(yctx, PROFILE)))
    assert plan.error and "$include" in plan.error
    res = project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, PROFILE)))
    assert res.status == "error" and p.read_text().startswith("{ agents")


def test_keyless_openai_gets_auth_none_other_protocols_a_placeholder(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='""'))
    provs = {o.path[2]: o.value for o in plan_of_target(yctx, AD, t).ops if o.path[0] == "models"}  # type: ignore[union-attr]
    assert provs["vmr"]["auth"] == "none" and "apiKey" not in provs["vmr"]
    assert provs["vmr-anthropic"]["apiKey"] == "dummy"


def test_literal_key_is_flagged(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-lit"'))
    assert any(w.field == "api_key" for w in plan_of_target(yctx, AD, t).warnings)


def test_removing_fast_removes_utility_model(yctx):
    seed(yctx, AD, "config", "openclaw/openclaw.json5")
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, PROFILE)))
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}')))
    assert "utilityModel" not in tree(yctx)["agents"]["defaults"]


def test_unsupported_roles_warn(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert {w.field for w in plan_of_target(yctx, AD, t).warnings} == {
        "roles.reasoning",
        "roles.subagent",
    }


def test_config_path_override(ctx, tmp_path):
    c = Ctx.from_env(
        {**ctx.env, "OPENCLAW_CONFIG_PATH": str(tmp_path / "x.json")}, interactive=False
    )
    assert AD.config_path(c) == tmp_path / "x.json"
    c = Ctx.from_env({**ctx.env, "OPENCLAW_CONFIG_PATH": "rel.json"}, interactive=False)
    assert AD.config_path(c) == c.home / ".openclaw" / "openclaw.json"


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        (("models", "providers", "vmr"), True),
        (("models", "providers"), False),
        (("models", "mode"), False),
        (("agents", "defaults", "model", "primary"), True),
        (("agents", "defaults", "model", "fallbacks"), False),
        (("agents", "defaults", "utilityModel"), True),
        (("agents", "list"), False),
        (("gateway", "port"), False),
    ],
)
def test_whitelist(path, ok):
    assert AD.is_managed("config", path) is ok


def test_launch_plan_is_exec_with_inline_override(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    spec = AD.plan_launch(
        t, yctx, LaunchContext(passthrough=["fix the tests"], bin_path="/bin/openclaw")
    )
    assert spec.argv[:3] == ["/bin/openclaw", "agent", "exec"] and spec.argv[-1] == "fix the tests"
    i = spec.argv.index("--config-override")
    ov = json.loads(spec.argv[i + 1])
    assert ov["models"]["providers"]["vmr"]["apiKey"] == "${VMR_KEY}"
    assert ov["agents"]["defaults"]["utilityModel"] == "vmr/cheap"
    assert spec.argv[spec.argv.index("--model") + 1] == "vmr/coding"
    assert "sk-gw" not in " ".join(spec.argv) and any("unverified" in n for n in spec.notes)


def test_launch_with_literal_key(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-lit"'))
    spec = AD.plan_launch(t, yctx, LaunchContext())
    assert spec.env == {"ACM_RUN_KEY": "sk-lit"} and "sk-lit" not in " ".join(spec.argv)


def test_static_anthropic_provider(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          a:
            protocol: anthropic-messages
            base_url: https://x
            api_key: "${VMR_KEY}"
            models:
              m: {input: [text, image], max_output_tokens: 8000}
        profiles:
          p: {default: m}
        """
    )
    project(yctx, AD, target_of(yctx, AD, cfg, "p"))
    prov = tree(yctx)["models"]["providers"]["a"]
    assert prov["api"] == "anthropic-messages" and prov["models"] == [
        {"id": "m", "name": "m", "input": ["text", "image"], "maxTokens": 8000}
    ]
