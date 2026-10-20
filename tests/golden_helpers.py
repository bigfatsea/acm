"""Helpers for adapter golden tests: config text -> ResolvedTarget -> applied files."""

import json
import shutil
import textwrap
from pathlib import Path

from fakes import team_manifest

from acm.adapters.base import Adapter, DocView
from acm.catalog.model import ResolvedTarget
from acm.catalog.resolve import build_catalog, resolve_target
from acm.config.load import parse_config_text
from acm.core.context import Ctx
from acm.engine.apply import apply_agent
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.model import ApplyResult, Plan

FIXTURES = Path(__file__).parent / "fixtures"

TEAM_PROFILE = '{default: "vmr@default", roles: {reasoning: "vmr@reasoning", fast: "vmr@fast", subagent: "vmr@subagent", review: "vmr@review"}}'


def manifest_config(
    ctx: Ctx, profile: str = TEAM_PROFILE, key: str = '"${VMR_KEY}"', manifest: dict | None = None
) -> str:
    """Config with a file-backed manifest provider named vmr (no network)."""
    mpath = ctx.home / "manifest.json"
    mpath.write_text(json.dumps(manifest or team_manifest("http://gw.test")))
    return textwrap.dedent(
        f"""
        version: 4
        providers:
          vmr: {{manifest: "{mpath}", api_key: {key}}}
        profiles:
          team: {profile}
        """
    )


def target_of(ctx: Ctx, adapter: Adapter, cfg_text: str, profile: str = "team") -> ResolvedTarget:
    cfg = parse_config_text(cfg_text)
    cat = build_catalog(ctx, cfg)
    assert not cat.errors, cat.errors
    return resolve_target(cfg, cat, profile, adapter.protocols, adapter.id)


def plan_of_target(ctx: Ctx, adapter: Adapter, target: ResolvedTarget) -> Plan:
    return adapter.plan_files(target, ctx, DocView(ctx, adapter.files(ctx)))


def seed(ctx: Ctx, adapter: Adapter, logical: str, fixture: str) -> Path:
    """Copy tests/fixtures/<fixture> to where the adapter keeps ``logical``."""
    dest = next(s.path for s in adapter.files(ctx) if s.logical == logical)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / fixture, dest)
    return dest


def project(ctx: Ctx, adapter: Adapter, target: ResolvedTarget) -> ApplyResult:
    plan = plan_of_target(ctx, adapter, target)
    log = HistoryLog(ctx)
    return apply_agent(
        ctx, adapter, plan, cmd="acm use team", op=log.new_op(), log=log, store=ObjectStore(ctx)
    )  # fmt: skip
