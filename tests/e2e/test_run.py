import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from fakes import team_manifest

from acm.cli.output import Out
from acm.core.context import Ctx
from acm.core.errors import ConfigError, NotFoundError
from acm.run.runner import cleanup_stale_run_dirs, run_agent, substitute

pytestmark = pytest.mark.e2e

STUB = f"""#!{sys.executable}
import json, os, sys
info = {{"argv": sys.argv, "env": dict(os.environ), "files": {{}}}}
for a in sys.argv:
    if "model_catalog_json=" in a:
        p = a.split("model_catalog_json=", 1)[1].strip('"')
        info["files"][p] = os.path.exists(p) and len(open(p).read())
json.dump(info, open(os.environ["ACM_STUB_OUT"], "w"))
"""


@pytest.fixture
def stubs(tmp_path):
    bindir = Path(os.environ["PATH"].split(os.pathsep)[0])

    def install(*names):
        for n in names:
            p = bindir / n
            p.write_text(STUB)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)

    return install


def cli(args, env, out_file):
    e = {**env, "ACM_STUB_OUT": str(out_file), "PYTHONPATH": ""}
    return subprocess.run(
        [sys.executable, "-m", "acm", *args], env=e, capture_output=True, text=True, timeout=60
    )


@pytest.fixture
def envs(team, ctx):
    return {**ctx.env, "VMR_URL": team.url, "VMR_KEY": team.key}


def test_zero_config_exec_mode(envs, stubs, tmp_path, ctx):
    stubs("claude")
    out_file = tmp_path / "stub.json"
    p = cli(["run", "claude", "--", "-p", "hello"], envs, out_file)
    assert p.returncode == 0, p.stderr
    info = json.loads(out_file.read_text())
    assert info["argv"][1] == "--settings" and info["argv"][-2:] == ["-p", "hello"]
    settings = json.loads(info["argv"][2])
    assert settings["model"] == "claude" and settings["apiKeyHelper"] == "printenv VMR_KEY"
    assert envs["VMR_KEY"] not in " ".join(info["argv"])
    assert info["env"]["VMR_KEY"] == envs["VMR_KEY"]  # reaches the agent through the environment
    # nothing was written anywhere
    assert not ctx.history_path.exists() and not ctx.config_path.exists()
    assert not (ctx.home / ".claude").exists()


def test_model_flag_forms(envs, stubs, tmp_path):
    stubs("opencode")
    for m, expect in (
        ("cheap", "vmr/cheap"),
        ("vmr.agent", "vmr/agent"),
        ("@reasoning", "vmr/agent"),
    ):
        out_file = tmp_path / "o.json"
        p = cli(["run", "opencode", "-m", m, "--", "run", "hi"], envs, out_file)
        assert p.returncode == 0, p.stderr
        inline = json.loads(json.loads(out_file.read_text())["env"]["OPENCODE_CONFIG_CONTENT"])
        assert inline["model"] == expect


def test_agent_shorthand(envs, stubs, tmp_path):
    stubs("claude")
    out_file = tmp_path / "s.json"
    p = cli(["claude", "--", "-p", "x"], envs, out_file)
    assert p.returncode == 0, p.stderr
    assert json.loads(out_file.read_text())["argv"][-2:] == ["-p", "x"]


def test_child_mode_writes_a_private_catalog_and_removes_it(envs, stubs, tmp_path, ctx):
    stubs("codex")
    out_file = tmp_path / "c.json"
    p = cli(["run", "codex", "--", "exec", "hi"], envs, out_file)
    assert p.returncode == 0, p.stderr
    info = json.loads(out_file.read_text())
    ((path, size),) = info["files"].items()
    assert path.startswith(str(ctx.run_dir)) and size > 1000  # existed while the agent ran
    assert not Path(path).exists() and not any(ctx.run_dir.iterdir())  # and is gone after
    assert envs["VMR_KEY"] not in " ".join(info["argv"])


def test_exit_code_of_the_agent_is_returned(envs, tmp_path):
    bindir = Path(os.environ["PATH"].split(os.pathsep)[0])
    p = bindir / "codex"
    p.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(7)\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    assert cli(["run", "codex", "--", "x"], envs, tmp_path / "x").returncode == 7


def test_errors(envs, stubs, tmp_path):
    out_file = tmp_path / "e.json"
    p = cli(["run", "claude"], envs, out_file)  # binary not installed
    assert p.returncode == 4 and "not found on PATH" in p.stderr
    p = cli(["run", "nonesuch"], envs, out_file)
    assert p.returncode == 4 and "unknown agent" in p.stderr
    stubs("claude")
    no_gateway = {k: v for k, v in envs.items() if k not in ("VMR_URL", "ACM_MANIFEST")}
    p = cli(["run", "claude"], no_gateway, out_file)
    assert p.returncode == 1 and "nothing to start from" in p.stderr
    p = cli(["run", "openclaw"], envs, out_file)
    assert p.returncode == 4  # openclaw is not installed


def test_t2_family_member_launch_is_refused(envs, stubs, tmp_path):
    stubs("mimo")
    p = cli(["run", "mimocode", "--", "hi"], envs, tmp_path / "t.json")
    assert p.returncode == 1 and "disabled until" in p.stderr


def test_unauthorised_gateway_is_a_clear_error(envs, stubs, tmp_path):
    stubs("claude")
    bad = {**envs, "VMR_KEY": "wrong"}
    p = cli(["run", "claude"], bad, tmp_path / "u.json")
    assert p.returncode == 1 and "refused the credential" in p.stderr


def test_config_mode_uses_the_active_profile_and_dash_m(team, envs, stubs, tmp_path, ctx):
    stubs("claude")
    env = {k: v for k, v in envs.items() if k != "VMR_URL"}
    assert cli(["init", "--vmr", team.url, "--yes"], env, tmp_path / "i").returncode == 0
    p = cli(
        ["run", "claude", "--profile", "daily", "-m", "vmr@reasoning", "--", "x"],
        env,
        tmp_path / "r.json",
    )
    assert p.returncode == 0, p.stderr
    settings = json.loads(json.loads((tmp_path / "r.json").read_text())["argv"][2])
    assert settings["model"] == "agent"
    p = cli(["run", "claude", "--profile", "nope"], env, tmp_path / "r2.json")
    assert p.returncode == 4


def test_secret_env_for_literal_keys_is_private_to_the_child(team, stubs, tmp_path, ctx):
    stubs("opencode")
    cfg = ctx.acm_home / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        f'version: 4\nproviders:\n  vmr: {{manifest: "{team.url}/manifest", api_key: "{team.key}"}}\n'
        "profiles:\n  p: {default: vmr@default}\n"
    )
    env = {**ctx.env}
    p = cli(["run", "opencode", "--profile", "p", "--", "run", "hi"], env, tmp_path / "l.json")
    assert p.returncode == 0, p.stderr
    info = json.loads((tmp_path / "l.json").read_text())
    assert info["env"]["ACM_RUN_KEY"] == team.key
    assert team.key not in " ".join(info["argv"]) + info["env"]["OPENCODE_CONFIG_CONTENT"]


# ------------------------------------------------------------- in-process pieces


class FakeExec:
    def __init__(self):
        self.calls = []

    def replace_process(self, argv, env):
        self.calls.append(("exec", argv, dict(env)))
        raise SystemExit(0)

    def run_child(self, argv, env):
        self.calls.append(("child", argv, dict(env)))
        return 3


def test_runner_with_fake_executor(team, ctx, stubs):
    stubs("codex")
    c = Ctx.from_env({**ctx.env, "VMR_URL": team.url, "VMR_KEY": team.key}, interactive=False)
    ex = FakeExec()
    code = run_agent(
        c,
        Out(no_color=True),
        "codex",
        model=None,
        profile=None,
        manifest=None,
        passthrough=["exec", "hi"],
        executor=ex,
    )
    assert code == 3 and ex.calls[0][0] == "child"
    assert not (c.run_dir / str(os.getpid())).exists()


def test_substitute_and_stale_cleanup(ctx, tmp_path):
    from acm.adapters.base import LaunchSpec

    spec = LaunchSpec(argv=["x", "@@RUN_DIR@@/a"], env={"K": "@@RUN_DIR@@"})
    argv, env = substitute(spec, tmp_path)
    assert argv[1] == f"{tmp_path}/a" and env["K"] == str(tmp_path)
    dead = ctx.run_dir / "999999"
    dead.mkdir(parents=True)
    alive = ctx.run_dir / str(os.getpid())
    alive.mkdir()
    cleanup_stale_run_dirs(ctx)
    assert not dead.exists() and alive.exists()


def test_run_config_errors(ctx):
    from acm.run.runner import run_config

    with pytest.raises(ConfigError, match="nothing to start from"):
        run_config(ctx, None, None, None)
    ctx.acm_home.mkdir(parents=True)
    ctx.config_path.write_text(
        'version: 4\nproviders:\n  a: {protocol: openai-completions, base_url: "http://x/v1", models: {m: {}}}\n'
        "profiles:\n  p: {default: m}\n"
    )
    with pytest.raises(ConfigError, match="no profile selected"):
        run_config(ctx, None, None, None)
    with pytest.raises(NotFoundError):
        run_config(ctx, None, "zzz", None)
    cfg, name = run_config(ctx, "a.m", "p", None)
    assert name == "p" and cfg.profiles["p"].default == "a.m"


def test_zero_config_manifest_file(ctx, tmp_path):
    from acm.run.runner import zero_config

    f = tmp_path / "m.json"
    f.write_text(json.dumps(team_manifest("http://gw")))
    cfg = zero_config(ctx, str(f), None)
    assert cfg.profiles["run"].default == "vmr@default" and "fast" in cfg.profiles["run"].roles
