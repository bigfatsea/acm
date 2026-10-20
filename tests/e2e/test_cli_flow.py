import json

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture
def setup(team, stub_agents, claude_home, acm):
    stub_agents("claude")
    code, out, err = acm("init", "--vmr", team.url, "--yes")
    assert code == 0, err
    return team


def test_init_writes_a_manifest_config_and_refuses_to_overwrite(team, stub_agents, acm, ctx):
    stub_agents("claude")
    code, out, err = acm("init", "--vmr", team.url, "--yes")
    assert code == 0 and "Wrote" in out and "Claude Code" in out
    text = ctx.config_path.read_text()
    assert "manifest:" in text and "${VMR_KEY}" in text and team.key not in text
    assert oct(ctx.config_path.stat().st_mode & 0o777) == "0o600"
    code, out, err = acm("init", "--vmr", team.url, "--yes")
    assert code == 1 and "already exists" in err
    code, out, err = acm("init", "--vmr", team.url, "--yes", "--force")
    assert code == 0 and (ctx.config_path.with_name("config.yaml.bak")).exists()


def test_init_needs_confirmation_when_not_interactive(team, acm, ctx):
    code, out, err = acm("init", "--vmr", team.url)
    assert code == 2 and "--yes" in err and not ctx.config_path.exists()


def test_init_with_gateway_that_wants_a_key(team, monkeypatch, acm):
    monkeypatch.delenv("VMR_KEY")
    code, out, err = acm("init", "--vmr", team.url, "--yes")
    assert code == 1 and "VMR_KEY" in err


def test_init_without_any_gateway_offers_the_template(acm, ctx):
    code, out, err = acm("init", "--yes")
    assert code == 0 and "starter template" in out and "anthropic" in ctx.config_path.read_text()
    code, out, err = acm("init", "--vmr", "http://127.0.0.1:9", "--yes", "--force")
    assert code == 4 and "no gateway found" in err


def test_use_dry_run_then_apply_then_noop(setup, acm, claude_home):
    before = claude_home.read_text()
    code, out, err = acm("use", "daily", "--dry-run")
    assert code == 0 and "would change" in out and "ANTHROPIC_BASE_URL" in out
    assert claude_home.read_text() == before
    code, out, err = acm("use", "daily", "--yes")
    assert code == 0 and "written" in out
    s = json.loads(claude_home.read_text())
    assert s["model"] == "claude" and s["permissions"]["allow"] == ["Bash(git status)"]
    code, out, err = acm("use", "daily", "--yes")
    assert code == 0 and "noop" in out
    code, out, err = acm("status")
    assert code == 0 and "SYNCED" in out and "Active profile: daily" in out


def test_use_needs_yes_for_the_first_takeover(setup, acm, claude_home):
    code, out, err = acm("use", "daily")
    assert code == 2 and "blocked" in out and "--yes" in err + out


def test_drift_is_reported_blocked_and_forced(setup, acm, claude_home):
    acm("use", "daily", "--yes")
    claude_home.write_text(claude_home.read_text().replace('"model": "claude"', '"model": "hand"'))
    code, out, err = acm("status")
    assert code == 2 and "DRIFTED" in out and "hand" in out
    code, out, err = acm("use", "daily", "--yes")
    assert code == 2 and "blocked" in out and "--force" in err
    code, out, err = acm("use", "daily", "--yes", "--force")
    assert code == 0 and json.loads(claude_home.read_text())["model"] == "claude"


def test_catalog_change_shows_as_out_of_sync_and_apply_picks_it_up(setup, acm, claude_home):
    acm("use", "daily", "--yes")
    team = setup
    for m in team.manifest["models"]:
        if m["id"] == "cheap":
            m["roles"] = []
        if m["id"] == "resp":
            m["roles"] = ["fast"] if False else m["roles"]
    team.manifest["models"].append(
        {"id": "mini", "protocols": ["anthropic-messages"], "roles": ["fast"]}
    )
    team.etag = '"v2"'
    code, out, err = acm("status")
    assert code == 0 and "OUT_OF_SYNC" in out and "HAIKU" in out
    code, out, err = acm("apply")
    assert code == 0 and "written" in out
    assert json.loads(claude_home.read_text())["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "mini"
    code, out, err = acm("status")
    assert "SYNCED" in out


def test_history_rollback_and_restore_baseline(setup, acm, claude_home):
    original = claude_home.read_text()
    acm("use", "daily", "--yes")
    code, out, err = acm("history")
    assert (
        code == 0
        and "baseline" in out
        and "write" in out
        and "model: 'claude'" not in out.split("write")[0]
    )
    assert "model:" in out and "(absent) -> 'claude'" in out
    code, out, err = acm("rollback")
    assert code == 0 and "written" in out
    assert "ANTHROPIC_BASE_URL" not in claude_home.read_text()
    acm("use", "daily", "--yes")
    code, out, err = acm("restore", "--baseline")
    assert code == 0 and claude_home.read_text() == original
    code, out, err = acm("status")
    assert "UNMANAGED" in out
    code, out, err = acm("use", "daily", "--yes")
    assert code == 0 and "written" in out


def test_restore_argument_errors(setup, acm):
    acm("use", "daily", "--yes")
    code, out, err = acm("restore")
    assert code == 1 and "exactly one" in err
    code, out, err = acm("restore", "999")
    assert code == 4 and "no operation #999" in err
    code, out, err = acm("restore", "1", "--baseline")
    assert code == 1


def test_restore_whole_file_needs_confirmation_when_it_discards_changes(setup, acm, claude_home):
    acm("use", "daily", "--yes")
    claude_home.write_text(claude_home.read_text().replace('"X": "1"', '"X": "2"'))
    code, out, err = acm("restore", "--baseline", "--file")
    assert code == 2 and "discard" in err
    code, out, err = acm("restore", "--baseline", "--file", "--yes")
    assert code == 0 and '"X": "1"' in claude_home.read_text()


def test_prune_keeps_baseline(setup, acm):
    acm("use", "daily", "--yes")
    acm("use", "daily", "--yes", "--force")
    assert acm("prune", "--keep", "0")[0] == 1  # would drop the drift reference
    code, out, err = acm("prune", "--keep", "1")
    assert code == 0 and "Removed" in out
    code, out, err = acm("history")
    assert "baseline" in out


def test_error_exit_codes(setup, acm):
    assert acm("use", "nope")[0] == 4
    assert acm("use", "daily", "pi")[0] == 4  # unknown/undetected agent
    assert acm("use", "daily", "claude", "--yes")[0] == 0
    assert acm("status", "nonexistent")[0] == 4


def test_missing_config_and_unset_key(team, stub_agents, acm, monkeypatch):
    stub_agents("claude")
    assert acm("status")[0] == 1
    acm("init", "--vmr", team.url, "--yes")
    monkeypatch.delenv("VMR_KEY")
    code, out, err = acm("use", "daily", "--yes")
    assert (code == 1 and "refused" in err) or "VMR_KEY" in err


def test_unreachable_gateway_fails_before_writing_anything(setup, acm, claude_home):
    setup.stop()
    before = claude_home.read_text()
    code, out, err = acm("use", "daily", "--yes")
    assert (code == 3 and "no cached manifest" in err) or "cached" in err
    assert claude_home.read_text() == before


def test_unreachable_gateway_with_cache_still_works_and_says_so(setup, acm):
    acm("use", "daily", "--yes")
    setup.stop()
    code, out, err = acm("status")
    assert code == 0 and "served from cache" in err


def test_version_flag(acm):
    code, out, err = acm("--version")
    assert code == 0 and out.strip().startswith("0.4.0")


def test_released_agent_is_skipped_until_named_again(setup, acm, claude_home, ctx):
    assert acm("use", "daily", "--yes")[0] == 0
    assert acm("restore", "--baseline", "--yes")[0] == 0
    original = claude_home.read_text()
    code, out, err = acm("use", "daily", "--yes")
    assert code == 0 and "skipped" in out and "acm use daily claude_code" in out
    assert claude_home.read_text() == original
    code, out, err = acm("status")
    assert "UNMANAGED" in out
    code, out, err = acm("use", "daily", "claude")  # naming it is a takeover: confirm
    assert code == 2 and "--yes" in err and claude_home.read_text() == original
    code, out, err = acm("use", "daily", "claude", "--yes")
    assert code == 0 and "written" in out
    assert json.loads((ctx.state_dir / "managed.json").read_text()) == ["claude_code"]


def test_active_profile_changes_only_after_a_projection(stub_agents, claude_home, acm, ctx):
    stub_agents("claude")
    ctx.config_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.config_path.write_text(
        "version: 4\nproviders:\n"
        "  an:\n    protocol: anthropic-messages\n    base_url: https://a.example.com\n"
        "    models: {m1: {}}\n"
        "  oa:\n    protocol: openai-completions\n    base_url: https://o.example.com/v1\n"
        "    models: {o1: {}}\n"
        "profiles:\n  good: {default: an.m1}\n  bad: {default: oa.o1}\n"
    )
    assert acm("use", "good", "--yes")[0] == 0
    code, out, err = acm("use", "bad", "--yes")  # Claude Code cannot speak openai-completions
    assert code == 2 and "active profile was not changed" in err
    assert (ctx.state_dir / "active").read_text().strip() == "good"


def test_drift_message_masks_secrets(team, stub_agents, claude_home, acm, ctx):
    stub_agents("claude")
    ctx.config_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.config_path.write_text(
        "version: 4\nproviders:\n  ds:\n    protocol: anthropic-messages\n"
        "    base_url: https://api.example.com\n    api_key: sk-literal-secret-0001\n"
        "    models: {m1: {}}\nprofiles:\n  a: {default: ds.m1}\n"
    )
    assert acm("use", "a", "--yes")[0] == 0
    claude_home.write_text(
        claude_home.read_text().replace("sk-literal-secret-0001", "sk-rotated-secret-0002")
    )
    code, out, err = acm("use", "a")
    assert code == 2 and "ANTHROPIC_AUTH_TOKEN" in err
    assert "secret-0001" not in err and "secret-0002" not in err


def test_init_force_backup_is_private(setup, team, acm, ctx):
    assert acm("init", "--vmr", team.url, "--yes", "--force")[0] == 0
    bak = ctx.config_path.with_name("config.yaml.bak")
    assert oct(bak.stat().st_mode & 0o777) == "0o600"


def test_noop_does_not_repeat_projection_warnings(setup, acm):
    code, out, err = acm("use", "daily", "--yes")
    assert code == 0 and "[claude_code]" in err
    code, out, err = acm("use", "daily", "--yes")
    assert code == 0 and "noop" in out and "[claude_code]" not in err
    code, out, err = acm("apply", "--verbose")
    assert "[claude_code]" in err
