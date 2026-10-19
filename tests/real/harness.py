"""Run a real agent binary against a local mock gateway in an isolated HOME.

This is the "does the projection actually work?" check: after ``acm use`` (or ``acm run``)
the real agent must send its request to the mock gateway, naming the expected model and
carrying the expected credential.
"""

import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fake_gateway import FakeGateway
from fakes import team_manifest

from acm.adapters.base import Adapter, DocView, LaunchContext
from acm.catalog.resolve import build_catalog, resolve_target
from acm.config.load import parse_config_text
from acm.core.context import Ctx
from acm.engine.apply import apply_agent
from acm.engine.history import HistoryLog, ObjectStore

GW_KEY = "sk-gw-123"


@dataclass
class RealRig:
    adapter: Adapter
    gateway: FakeGateway
    home: Path
    ctx: Ctx
    env: dict[str, str]
    profile: str = "team"
    extra_roles: bool = True

    def config_text(self) -> str:
        roles = (
            ', roles: {reasoning: "vmr@reasoning", fast: "vmr@fast", subagent: "vmr@subagent"}'
            if self.extra_roles
            else ""
        )
        return textwrap.dedent(
            f"""
            version: 4
            providers:
              vmr: {{manifest: "{self.gateway.url}/manifest", api_key: "${{VMR_KEY}}"}}
            profiles:
              team: {{default: "vmr@default"{roles}}}
            """
        )

    def target(self) -> Any:
        cfg = parse_config_text(self.config_text())
        cat = build_catalog(self.ctx, cfg)
        assert not cat.errors, cat.errors
        return resolve_target(cfg, cat, self.profile, self.adapter.protocols, self.adapter.id)

    def project(self) -> Any:
        target = self.target()
        plan = self.adapter.plan_files(
            target, self.ctx, DocView(self.ctx, self.adapter.files(self.ctx))
        )
        assert plan.error is None, plan.error
        log = HistoryLog(self.ctx)
        res = apply_agent(
            self.ctx, self.adapter, plan, cmd="acm use team", op=log.new_op(), log=log,
            store=ObjectStore(self.ctx),
        )  # fmt: skip
        assert res.status in ("written", "noop"), (res.status, res.message)
        return res

    def launch_spec(self, passthrough: list[str]) -> Any:
        return self.adapter.plan_launch(
            self.target(), self.ctx,
            LaunchContext(passthrough=passthrough, bin_path=self.adapter.find_bin(self.ctx)),
        )  # fmt: skip

    def run(
        self, argv: list[str], extra_env: dict[str, str] | None = None, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **(extra_env or {})}
        return subprocess.run(
            argv, env=env, capture_output=True, text=True, timeout=timeout, cwd=str(self.home),
            stdin=subprocess.DEVNULL,
        )  # fmt: skip

    def inference_posts(self, suffix: str) -> list[dict[str, Any]]:
        return [
            r for r in self.gateway.requests if r["method"] == "POST" and r["path"].endswith(suffix)
        ]


def make_rig(tmp_path: Path, adapter: Adapter) -> RealRig:
    gw = FakeGateway(key=GW_KEY).start()
    gw.manifest = team_manifest(gw.url)
    home = tmp_path / "realhome"
    home.mkdir()
    env = {"HOME": str(home), "PATH": os.environ["REAL_PATH"], "VMR_KEY": GW_KEY, "TERM": "dumb"}
    ctx = Ctx.from_env(env, interactive=False, yes=True)
    return RealRig(adapter, gw, home, ctx, env)


def real_path() -> str:
    """The PATH real agents need (the test fixture strips PATH for ordinary tests)."""
    return os.environ.get("REAL_PATH", "")


def binary(name: str) -> str | None:
    return shutil.which(name, path=os.environ.get("REAL_PATH"))
