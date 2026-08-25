# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Golden tests for Claude Code adapter (WP6): Apply, Non-destructive, Rollback."""

import hashlib
import json
from pathlib import Path

from conftest import make_mock_profile

from acm.adapters import claude_code
from acm.safety import write_changeset
from acm.state import get_snapshots_dir, load_last_write
from acm.writers.json_editor import read_json_path
from acm.writers.tree_diff import tree_diff


def test_claude_code_golden_abc(tmp_home: Path) -> None:
    """Execute Golden a/b/c assertion suite for Claude Code."""
    fixture_src = Path(__file__).parent.parent / "fixtures" / "claude_code" / "settings.golden.json"
    initial_content = fixture_src.read_text(encoding="utf-8")
    initial_sha = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()

    # Setup target file in fake home
    claude_dir = tmp_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    target_file = claude_dir / "settings.json"
    target_file.write_text(initial_content, encoding="utf-8")

    # 1. Plan operations for profile
    profile = make_mock_profile(model_id="claude-3-7-sonnet-20250219")
    ops, _warnings = claude_code.plan(profile)
    assert len(ops) >= 3

    # ── Step a: Apply ─────────────────────────────────────────
    res = write_changeset(
        agent_id=claude_code.AGENT_ID,
        profile_name="daily",
        allowed_paths=claude_code.config_paths(),
        allowed_namespaces=claude_code.managed_namespaces(),
        ops=ops,
    )
    assert not res.noop
    assert res.backup_id is not None

    updated_content = target_file.read_text(encoding="utf-8")
    assert read_json_path(updated_content, "model") == "claude-3-7-sonnet-20250219"
    assert read_json_path(updated_content, "env.ANTHROPIC_BASE_URL") == "http://localhost:8800"
    assert read_json_path(updated_content, "env.ANTHROPIC_AUTH_TOKEN") == "mock_key"

    # ── Step b: Non-destructive assertion ──────────────────────
    parsed_before = json.loads(initial_content)
    parsed_after = json.loads(updated_content)
    diffs = tree_diff(parsed_before, parsed_after, claude_code.managed_namespaces())
    assert diffs == []  # Unmanaged fields (permissions, custom env, plugins) 100% untouched!

    assert read_json_path(updated_content, "permissions.allow_read") is True
    assert read_json_path(updated_content, "env.USER_CUSTOM_VAR") == "keep_this_custom_env_val"
    assert read_json_path(updated_content, "enabledPlugins") == ["git", "formatter"]

    # ── Step c: Rollback ───────────────────────────────────────
    lw = load_last_write(claude_code.AGENT_ID)
    assert lw is not None
    snap_file = get_snapshots_dir(claude_code.AGENT_ID) / lw.backup_id / "settings.json"
    assert snap_file.exists()

    # Restore snapshot bytes
    target_file.write_bytes(snap_file.read_bytes())
    restored_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
    assert restored_sha == initial_sha


def test_claude_code_pool_aggregate_warning() -> None:
    """Type II agent: pool members beyond main produce one aggregate skip warning."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    prov = ResolvedProvider(
        name="vmr", protocol="anthropic", base_url="http://localhost:8800", api_key="k",
        raw_api_key_ref="${KEY}",
    )
    coding = ResolvedModel(model_id="coding", upstream_id="coding", provider=prov)
    cheap = ResolvedModel(model_id="cheap", upstream_id="cheap", provider=prov)
    agent = ResolvedModel(model_id="agent", upstream_id="agent-v2", provider=prov)
    profile = ResolvedProfile(
        profile_name="daily",
        main=coding,
        pool={"main": coding, "budget": cheap, "longctx": agent},
    )

    ops, warnings = claude_code.plan(profile)

    assert next(o.new for o in ops if o.path == "model") == "coding"
    pool_warnings = [w for w in warnings if w.field == "pool"]
    assert len(pool_warnings) == 1
    assert "budget(cheap)" in pool_warnings[0].reason
    assert "longctx(agent-v2)" in pool_warnings[0].reason
    assert "main(coding)" not in pool_warnings[0].reason


def test_claude_code_pool_skipped_includes_cross_provider_same_id() -> None:
    """§16.1 fix: skipped-members are compared by (provider, upstream id), not
    bare id — a pool member on a different provider with the same id string as
    main is a distinct, unexpressed model and must still be listed."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    vmr = ResolvedProvider(
        name="vmr", protocol="anthropic", base_url="http://localhost:8800", api_key="k",
        raw_api_key_ref="${KEY}",
    )
    direct = ResolvedProvider(
        name="direct", protocol="openai", base_url="https://direct.example.com/v1",
        api_key="k2", raw_api_key_ref="${KEY2}",
    )
    coding = ResolvedModel(model_id="coding", upstream_id="coding", provider=vmr)
    alt = ResolvedModel(model_id="alt-alias", upstream_id="coding", provider=direct)

    profile = ResolvedProfile(
        profile_name="daily", main=coding, pool={"main": coding, "review": alt}
    )

    _, warnings = claude_code.plan(profile)

    pool_warnings = [w for w in warnings if w.field == "pool"]
    assert len(pool_warnings) == 1
    assert "review(coding)" in pool_warnings[0].reason


def test_claude_code_pool_exempts_role_warning_for_covered_cheap() -> None:
    """§8.4: cheap role warning is suppressed only when its model is also a pool member."""
    from acm.resolve import ResolvedModel, ResolvedProfile, ResolvedProvider

    prov = ResolvedProvider(
        name="vmr", protocol="anthropic", base_url="http://localhost:8800", api_key="k",
        raw_api_key_ref="${KEY}",
    )
    coding = ResolvedModel(model_id="coding", upstream_id="coding", provider=prov)
    cheap = ResolvedModel(model_id="cheap", upstream_id="cheap", provider=prov)
    other = ResolvedModel(model_id="other", upstream_id="other", provider=prov)

    # cheap's model IS in the pool -> roles.cheap warning suppressed (covered by pool warning)
    profile_covered = ResolvedProfile(
        profile_name="daily", main=coding, cheap=cheap, pool={"main": coding, "budget": cheap}
    )
    _, warnings_covered = claude_code.plan(profile_covered)
    assert not any(w.field == "roles.cheap" for w in warnings_covered)

    # cheap's model is NOT in the pool -> roles.cheap warning still fires (not silently dropped)
    profile_uncovered = ResolvedProfile(
        profile_name="daily", main=coding, cheap=cheap, pool={"main": coding, "other": other}
    )
    _, warnings_uncovered = claude_code.plan(profile_uncovered)
    assert any(w.field == "roles.cheap" for w in warnings_uncovered)
