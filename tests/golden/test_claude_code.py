import json
import textwrap

import pytest
from golden_helpers import manifest_config, plan_of_target, project, seed, target_of

from acm.adapters.base import LaunchContext
from acm.adapters.claude_code import KEYLESS_PLACEHOLDER, ClaudeCode
from acm.core.context import Ctx
from acm.core.errors import ConfigError
from acm.engine.model import Delete, Set

pytestmark = pytest.mark.golden
AD = ClaudeCode()


@pytest.fixture
def yctx(ctx: Ctx) -> Ctx:
    return Ctx.from_env({**ctx.env, "VMR_KEY": "sk-gw"}, interactive=False, yes=True)


def settings(ctx):
    return json.loads(next(s.path for s in AD.files(ctx)).read_text())


def test_projection_on_a_realistic_settings_file(yctx):
    seed(yctx, AD, "settings", "claude_code/settings.json")
    t = target_of(yctx, AD, manifest_config(yctx))
    assert project(yctx, AD, t).status == "written"
    s = settings(yctx)
    assert s["model"] == "claude"
    assert s["apiKeyHelper"] == "printenv VMR_KEY"
    assert s["env"] == {
        "DISABLE_TELEMETRY": "1",
        "ANTHROPIC_BASE_URL": "http://gw.test",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "agent",
        "ANTHROPIC_DEFAULT_FABLE_MODEL": "agent",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "cheap",
        "CLAUDE_CODE_SUBAGENT_MODEL": "claude",
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "512000",
    }
    # everything the user had is still there
    orig = json.loads(
        (
            __import__("pathlib").Path(__file__).parents[1] / "fixtures/claude_code/settings.json"
        ).read_text()
    )
    for k in (
        "$schema",
        "permissions",
        "hooks",
        "enabledPlugins",
        "statusLine",
        "includeCoAuthoredBy",
    ):
        assert s[k] == orig[k]
    assert "sk-gw" not in json.dumps(s)


def test_second_projection_is_a_noop(yctx):
    seed(yctx, AD, "settings", "claude_code/settings.json")
    t = target_of(yctx, AD, manifest_config(yctx))
    project(yctx, AD, t)
    assert project(yctx, AD, t).status == "noop"


def test_user_anthropic_key_is_removed_so_it_is_never_sent_to_the_gateway(yctx):
    p = next(s.path for s in AD.files(yctx))
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps({"env": {"ANTHROPIC_API_KEY": "sk-ant-mine", "ANTHROPIC_AUTH_TOKEN": "tok"}})
    )
    project(yctx, AD, target_of(yctx, AD, manifest_config(yctx)))
    env = settings(yctx)["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env


def test_roles_fall_back_to_default_with_warnings(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, '{default: "vmr@default"}'))
    plan = plan_of_target(yctx, AD, t)
    fields = {w.field for w in plan.warnings}
    assert {"roles.reasoning", "roles.fast"} <= fields
    sets = {o.path[-1]: o.value for o in plan.ops if isinstance(o, Set)}
    assert sets["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude"
    assert sets["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude"
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in sets  # inherits the main model


def test_review_role_warns(yctx):
    t = target_of(yctx, AD, manifest_config(yctx))
    assert any(w.field == "roles.review" for w in plan_of_target(yctx, AD, t).warnings)


def test_literal_credential_is_written_with_a_warning(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, key='"sk-literal"'))
    plan = plan_of_target(yctx, AD, t)
    assert any(w.field == "api_key" for w in plan.warnings)
    token = [o for o in plan.ops if isinstance(o, Set) and o.path[-1] == "ANTHROPIC_AUTH_TOKEN"]
    assert token and token[0].value == "sk-literal"
    assert any(isinstance(o, Delete) and o.path == ("apiKeyHelper",) for o in plan.ops)


def test_keyless_gateway_gets_a_placeholder(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, key='""'))
    plan = plan_of_target(yctx, AD, t)
    token = [o for o in plan.ops if isinstance(o, Set) and o.path[-1] == "ANTHROPIC_AUTH_TOKEN"]
    assert token[0].value == KEYLESS_PLACEHOLDER


def test_unset_variable_is_a_hard_error_before_any_write(ctx):
    t = target_of(ctx, AD, manifest_config(ctx))
    with pytest.raises(ConfigError, match="VMR_KEY is not set"):
        plan_of_target(ctx, AD, t)
    assert not next(s.path for s in AD.files(ctx)).exists()


def test_static_provider_with_effort_and_context(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          anth:
            protocol: anthropic-messages
            base_url: https://api.example.com
            api_key: "${VMR_KEY}"
            models:
              big: {context_window: 400000, effort: high, roles: [default]}
        profiles:
          p: {default: big}
        """
    )
    t = target_of(yctx, AD, cfg, "p")
    project(yctx, AD, t)
    s = settings(yctx)
    assert s["effortLevel"] == "high" and s["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "400000"
    assert s["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com"


def test_removed_context_window_is_retired(yctx):
    cfg = textwrap.dedent(
        """
        version: 4
        providers:
          anth:
            protocol: anthropic-messages
            base_url: https://api.example.com
            api_key: "${VMR_KEY}"
            models:
              big: {context_window: 400000, roles: [default]}
        profiles:
          p: {default: big}
        """
    )
    project(yctx, AD, target_of(yctx, AD, cfg, "p"))
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" in settings(yctx)["env"]
    project(yctx, AD, target_of(yctx, AD, cfg.replace("context_window: 400000, ", ""), "p"))
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in settings(yctx)["env"]


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        (("model",), True),
        (("apiKeyHelper",), True),
        (("env", "ANTHROPIC_BASE_URL"), True),
        (("env", "ANTHROPIC_DEFAULT_HAIKU_MODEL"), True),
        (("hooks",), False),
        (("permissions", "allow"), False),
        (("env", "DISABLE_TELEMETRY"), False),
        (("env",), False),
    ],
)
def test_whitelist(path, ok):
    assert AD.is_managed("settings", path) is ok


def test_launch_plan_keeps_secrets_out_of_argv(yctx):
    t = target_of(yctx, AD, manifest_config(yctx))
    spec = AD.plan_launch(t, yctx, LaunchContext(passthrough=["-p", "hi"], bin_path="/bin/claude"))
    assert (
        spec.argv[0] == "/bin/claude"
        and spec.argv[1] == "--settings"
        and spec.argv[-2:] == ["-p", "hi"]
    )
    inline = json.loads(spec.argv[2])
    assert inline["apiKeyHelper"] == "printenv VMR_KEY" and inline["env"]["ANTHROPIC_API_KEY"] == ""
    assert "sk-gw" not in " ".join(spec.argv) and spec.env == {} and spec.mode == "exec"


def test_launch_plan_with_literal_key_uses_a_private_env_var(yctx):
    t = target_of(yctx, AD, manifest_config(yctx, key='"sk-literal"'))
    spec = AD.plan_launch(t, yctx, LaunchContext())
    assert spec.env == {"ACM_RUN_KEY": "sk-literal"} and "sk-literal" not in " ".join(spec.argv)
    assert json.loads(spec.argv[2])["apiKeyHelper"] == "printenv ACM_RUN_KEY"
    assert spec.secret_env == {"ACM_RUN_KEY"}


def _cannot_think(model_id: str) -> dict:
    """team_manifest with ``model_id`` known to have no thinking candidate (all declared)."""
    from fakes import team_manifest

    m = team_manifest("http://gw.test")
    for mm in m["models"]:
        if mm["id"] == model_id:
            mm.pop("reasoning", None)
            mm["guarantee"] = {"input": ["text"], "tool_call": True, "reasoning": False}
    return m


def test_slot_model_known_unable_to_think_warns(yctx):
    cfg = manifest_config(yctx, '{default: "vmr@default", roles: {fast: "vmr@fast"}}',
                          manifest=_cannot_think("cheap"))  # fmt: skip
    t = target_of(yctx, AD, cfg)
    assert t.role("fast").card.reasoning is False
    plan = plan_of_target(yctx, AD, t)
    hits = [w for w in plan.warnings if w.field == "models.cheap.reasoning"]
    assert len(hits) == 1 and "turns thinking on for every request" in hits[0].reason


def test_unknown_thinking_support_stays_quiet(yctx):
    t = target_of(
        yctx, AD, manifest_config(yctx, '{default: "vmr@default", roles: {fast: "vmr@fast"}}')
    )
    assert t.role("fast").card.reasoning is None  # no guarantee published: unknown, not "no"
    warns = plan_of_target(yctx, AD, t).warnings
    assert not [
        w for w in warns if w.field.startswith("models.") and w.field.endswith(".reasoning")
    ]
