import json
import textwrap

import pytest
from golden_helpers import manifest_config, plan_of_target, project, seed, target_of

from acm.adapters.base import LaunchContext, LaunchUnsupportedError
from acm.adapters.opencode import DEVECO, MIMO, OPENCODE, OpenCodeFamily
from acm.core.context import Ctx
from acm.formats.base import parse

pytestmark = pytest.mark.golden
AD = OpenCodeFamily(OPENCODE)
PROFILE = '{default: "vmr@default", roles: {fast: "vmr@fast", reasoning: "vmr@reasoning"}, models: {sonnet: "vmr.claude"}}'


@pytest.fixture
def yctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "VMR_KEY": "sk-gw"}, interactive=False, yes=True)


def tree(ctx, ad=AD):
    p = ad.files(ctx)[0].path
    return parse("jsonc", p.read_bytes()).tree()


def test_projection_preserves_comments_and_user_providers(yctx):
    path = seed(yctx, AD, "config", "opencode/opencode.jsonc")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert project(yctx, AD, t).status == "written"
    text = path.read_text()
    assert "// OpenCode configuration" in text and "// my local ollama" in text
    assert '"edit": "ask" // never let it edit silently' in text
    c = tree(yctx)
    assert c["theme"] == "tokyonight" and c["mcp"]["context7"]["type"] == "remote"
    assert set(c["provider"]) == {"ollama", "vmr", "vmr-anthropic"}
    assert c["model"] == "vmr/coding" and c["small_model"] == "vmr/cheap"
    vmr = c["provider"]["vmr"]
    assert vmr["npm"] == "@ai-sdk/openai-compatible"
    assert vmr["options"] == {"baseURL": "http://gw.test/v1", "apiKey": "{env:VMR_KEY}"}
    assert vmr["models"]["coding"]["limit"] == {"context": 200000, "output": 32000}
    assert vmr["models"]["agent"]["reasoning"] is True
    anth = c["provider"]["vmr-anthropic"]
    assert anth["npm"] == "@ai-sdk/anthropic" and anth["options"]["baseURL"] == "http://gw.test/v1"
    assert anth["models"]["claude"]["modalities"]["input"] == ["text", "image"]
    assert "sk-gw" not in text


def test_unknown_output_limit_is_defaulted_with_a_warning(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    plan = plan_of_target(yctx, AD, t)
    assert any(w.field == "models.coding.limit.output" for w in plan.warnings)


def test_second_projection_is_noop(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    project(yctx, AD, t)
    assert project(yctx, AD, t).status == "noop"


def test_small_model_is_removed_when_the_fast_role_goes_away(yctx):
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, PROFILE)))
    assert "small_model" in tree(yctx)
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}')))
    assert "small_model" not in tree(yctx)


def test_config_file_selection(yctx):
    d = yctx.home / ".config" / "opencode"
    assert AD.files(yctx)[0].path == d / "opencode.json"  # new file
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    assert AD.files(yctx)[0].path == d / "config.json"
    (d / "opencode.json").write_text("{}")
    assert AD.files(yctx)[0].path == d / "opencode.json"
    (d / "opencode.jsonc").write_text("{}")
    assert AD.files(yctx)[0].path == d / "opencode.jsonc"


def test_config_dir_overrides(ctx, tmp_path):
    c = Ctx.from_env({**ctx.env, "OPENCODE_CONFIG_DIR": str(tmp_path / "oc")}, interactive=False)
    assert AD.config_dir(c) == tmp_path / "oc"
    c = Ctx.from_env({**ctx.env, "XDG_CONFIG_HOME": str(tmp_path / "xdg")}, interactive=False)
    assert AD.config_dir(c) == tmp_path / "xdg" / "opencode"
    c = Ctx.from_env({**ctx.env, "MIMOCODE_HOME": str(tmp_path / "mimo")}, interactive=False)
    assert OpenCodeFamily(MIMO).config_dir(c) == tmp_path / "mimo" / "config"
    c = Ctx.from_env({**ctx.env, "DEVECO_CONFIG_DIR": "relative"}, interactive=False)
    assert OpenCodeFamily(DEVECO).config_dir(c) == c.home / ".config" / "deveco"


def test_family_members_share_the_mapping(yctx):
    for member in (MIMO, DEVECO):
        ad = OpenCodeFamily(member)
        assert ad.tier == "T2" and ad.files(yctx)[0].path.name == f"{member.stem}.json"
        project(yctx, ad, target_of(yctx, ad, manifest_config(yctx, PROFILE)))
        c = tree(yctx, ad)
        assert c["model"] == "vmr/coding" and "vmr" in c["provider"]


def test_t2_members_refuse_one_shot_launch(yctx):
    ad = OpenCodeFamily(MIMO)
    t = target_of(yctx, ad, manifest_config(yctx, PROFILE))
    with pytest.raises(LaunchUnsupportedError, match="inline-config"):
        ad.plan_launch(t, yctx, LaunchContext())


def test_literal_key_warns_and_keyless_has_no_apikey(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-lit"'))
    plan = plan_of_target(yctx, AD, t)
    assert any(w.field == "api_key" for w in plan.warnings)
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='""'))
    objs = [o.value for o in plan_of_target(yctx, AD, t).ops if o.path[0] == "provider"]  # type: ignore[union-attr]
    assert all("apiKey" not in o["options"] for o in objs)


def test_static_openai_responses_provider(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          r:
            protocol: openai-responses
            base_url: https://x/v1
            api_key: "${VMR_KEY}"
            models:
              m: {context_window: 100000, max_output_tokens: 8000, tool_call: true}
        profiles:
          p: {default: m}
        """
    )
    project(yctx, AD, target_of(yctx, AD, cfg, "p"))
    c = tree(yctx)
    assert c["provider"]["r"]["npm"] == "@ai-sdk/openai"
    assert c["provider"]["r"]["models"]["m"] == {
        "name": "m", "tool_call": True, "limit": {"context": 100000, "output": 8000},
    }  # fmt: skip


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        (("model",), True),
        (("small_model",), True),
        (("provider", "vmr"), True),
        (("provider",), False),
        (("provider", "vmr", "options"), False),
        (("mcp",), False),
        (("permission", "edit"), False),
    ],
)
def test_whitelist(path, ok):
    assert AD.is_managed("config", path) is ok


def test_launch_plan(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    spec = AD.plan_launch(
        t, yctx, LaunchContext(passthrough=["run", "hi"], bin_path="/bin/opencode")
    )
    assert spec.argv == ["/bin/opencode", "run", "hi"] and spec.mode == "exec"
    inline = json.loads(spec.env["OPENCODE_CONFIG_CONTENT"])
    assert inline["model"] == "vmr/coding" and inline["small_model"] == "vmr/cheap"
    assert inline["provider"]["vmr"]["options"]["apiKey"] == "{env:VMR_KEY}"
    assert "sk-gw" not in json.dumps(spec.env)


def test_launch_with_literal_key(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE, key='"sk-lit"'))
    spec = AD.plan_launch(t, yctx, LaunchContext())
    assert spec.env["ACM_RUN_KEY"] == "sk-lit"
    assert "sk-lit" not in spec.env["OPENCODE_CONFIG_CONTENT"]
    assert "{env:ACM_RUN_KEY}" in spec.env["OPENCODE_CONFIG_CONTENT"]
