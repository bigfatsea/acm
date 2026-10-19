import textwrap

import pytest
from golden_helpers import manifest_config, plan_of_target, project, seed, target_of

from acm.adapters.base import LaunchContext, LaunchUnsupportedError
from acm.adapters.hermes import Hermes
from acm.core.context import Ctx
from acm.formats.base import parse

pytestmark = pytest.mark.golden
AD = Hermes()
PROFILE = '{default: "vmr@default", roles: {fast: "vmr@fast", subagent: "vmr@subagent", reasoning: "vmr@reasoning"}, models: {sonnet: "vmr.claude"}}'


@pytest.fixture
def yctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "VMR_KEY": "sk-gw"}, interactive=False, yes=True)


def tree(ctx):
    return parse("yaml", AD.files(ctx)[0].path.read_bytes()).tree()


def test_projection_on_a_realistic_config(yctx):
    path = seed(yctx, AD, "config", "hermes/config.yaml")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert project(yctx, AD, t).status == "written"
    c = tree(yctx)
    assert c["model"] == {
        "default": "coding",
        "provider": "custom:acm-vmr",
        "base_url": "",
        "context_length": 200000,
    }  # the old default/provider/base_url were replaced; no stale api_mode
    assert c["providers"]["acm-vmr"] == {
        "base_url": "http://gw.test/v1",
        "api_mode": "chat_completions",
        "models": {"coding": {}, "agent": {}, "cheap": {}},
        "key_env": "VMR_KEY",
    }
    assert c["providers"]["acm-vmr-anthropic"]["api_mode"] == "anthropic_messages"
    assert c["providers"]["acm-vmr-anthropic"]["models"] == {"claude": {}}
    for task in ("title_generation", "compression", "web_extract", "approval"):
        assert c["auxiliary"][task] == {
            "provider": "custom:acm-vmr", "model": "cheap", "base_url": "", "api_key": "",
        }  # fmt: skip
    assert c["auxiliary"]["vision"] == {"provider": "auto", "model": ""}  # untouched
    assert c["delegation"] == {"provider": "custom:acm-vmr", "model": "coding"}
    # user content intact
    assert c["terminal"] == {"backend": "local", "cwd": "."} and c["skills"]["external_dirs"]
    text = path.read_text()
    assert "# Hermes Agent configuration" in text and "# keep this" in text and "sk-gw" not in text


def test_fresh_install_model_sentinel_is_replaced_by_the_mapping(yctx):
    seed(yctx, AD, "config", "hermes/config.fresh.yaml")
    t = target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}'))
    assert project(yctx, AD, t).status == "written"
    c = tree(yctx)
    assert c["model"]["default"] == "coding" and c["model"]["provider"] == "custom:acm-vmr"
    assert c["terminal"] == {"backend": "local"}


def test_missing_file_is_created(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}'))
    assert project(yctx, AD, t).status == "written"
    assert tree(yctx)["model"]["provider"] == "custom:acm-vmr"


def test_second_projection_is_noop(yctx):
    seed(yctx, AD, "config", "hermes/config.yaml")
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    project(yctx, AD, t)
    assert project(yctx, AD, t).status == "noop"


def test_roles_without_a_slot_warn(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    assert {w.field for w in plan_of_target(yctx, AD, t).warnings} == {"roles.reasoning"}


def test_literal_key_is_flagged(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}', key='"sk-lit"'))
    plan = plan_of_target(yctx, AD, t)
    assert any(w.field == "api_key" for w in plan.warnings)


def test_removing_the_fast_role_retires_the_aux_overrides(yctx):
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, PROFILE)))
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}')))
    c = tree(yctx)
    assert (
        "auxiliary" not in c
        or "title_generation" not in c.get("auxiliary", {})
        or c["auxiliary"]["title_generation"] == {}
    )
    assert "provider" not in c.get("delegation", {})


def test_static_provider_in_responses_mode(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          r:
            protocol: openai-responses
            base_url: https://x/v1
            api_key: "${VMR_KEY}"
            models:
              m: {context_window: 50000}
        profiles:
          p: {default: m}
        """
    )
    project(yctx, AD, target_of(yctx, AD, cfg, "p"))
    c = tree(yctx)
    assert c["providers"]["acm-r"]["api_mode"] == "codex_responses"
    assert c["model"]["context_length"] == 50000


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        (("model",), True),
        (("model", "default"), True),
        (("model", "streaming"), False),
        (("providers", "acm-vmr"), True),
        (("providers", "openrouter"), False),
        (("auxiliary", "title_generation", "model"), True),
        (("auxiliary", "vision", "model"), False),
        (("auxiliary", "title_generation", "timeout"), False),
        (("delegation", "model"), True),
        (("delegation", "max_iterations"), False),
        (("terminal",), False),
    ],
)
def test_whitelist(path, ok):
    assert AD.is_managed("config", path) is ok


def test_launch_plan(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, PROFILE))
    spec = AD.plan_launch(t, yctx, LaunchContext(passthrough=["-q", "hi"], bin_path="/bin/hermes"))
    assert spec.argv == [
        "/bin/hermes", "chat", "--provider", "custom", "--base-url", "http://gw.test/v1",
        "-m", "coding", "-q", "hi",
    ]  # fmt: skip
    assert spec.env == {"OPENAI_API_KEY": "sk-gw"} and "sk-gw" not in " ".join(spec.argv)
    assert spec.secret_env == {"OPENAI_API_KEY"}


def test_launch_refuses_non_chat_defaults(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          a:
            protocol: anthropic-messages
            base_url: https://x
            api_key: "${VMR_KEY}"
            models:
              m: {}
        profiles:
          p: {default: m}
        """
    )
    t = target_of(yctx, AD, cfg, "p")
    with pytest.raises(LaunchUnsupportedError, match="OpenAI-compatible"):
        AD.plan_launch(t, yctx, LaunchContext())
