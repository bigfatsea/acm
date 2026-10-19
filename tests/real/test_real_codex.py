import pytest
from harness import GW_KEY, binary, make_rig

from acm.adapters.codex import Codex
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.restore import RestoreRequest, restore_agent

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(binary("codex") is None, reason="codex not installed"),
]

SEED = '# mine\nmodel = "gpt-5-codex"\n\n[projects."/x"]\ntrust_level = "trusted"\n'
PROMPT = ["exec", "--skip-git-repo-check", "reply with OK"]


@pytest.fixture
def rig(tmp_path):
    r = make_rig(tmp_path, Codex())
    cfg = r.home / ".codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text(SEED)
    yield r
    r.gateway.stop()


def assert_hit(rig):
    posts = rig.inference_posts("/v1/responses")
    assert posts, f"no request reached the gateway: {rig.gateway.requests}"
    assert posts[0]["body"]["model"] == "resp"
    assert posts[0]["headers"]["authorization"] == f"Bearer {GW_KEY}"


def test_persistent_projection_reaches_the_gateway(rig):
    rig.project()
    out = rig.run([rig.adapter.find_bin(rig.ctx), *PROMPT])
    assert out.returncode == 0, out.stderr
    assert "OK" in out.stdout and "Unknown model" not in out.stderr
    assert_hit(rig)
    text = (rig.home / ".codex" / "config.toml").read_text()
    assert '[projects."/x"]' in text and "# mine" in text
    assert GW_KEY not in text  # env_key, not the key


def test_the_generated_catalog_is_really_read_by_codex(rig):
    rig.project()
    catalog = rig.ctx.acm_home / "owned" / "codex" / "catalog.json"
    assert catalog.exists()
    catalog.write_text('{"models": [{"slug": "resp"}]}')  # negative control: invalid entry
    out = rig.run([rig.adapter.find_bin(rig.ctx), *PROMPT])
    assert out.returncode != 0 or "missing field" in out.stderr + out.stdout


def test_baseline_restore_removes_catalog_and_returns_config(rig):
    cfg = rig.home / ".codex" / "config.toml"
    rig.project()
    catalog = rig.ctx.acm_home / "owned" / "codex" / "catalog.json"
    assert catalog.exists() and cfg.read_text() != SEED
    log = HistoryLog(rig.ctx)
    res = restore_agent(
        rig.ctx,
        rig.adapter,
        RestoreRequest("baseline"),
        cmd="x",
        op=log.new_op(),
        log=log,
        store=ObjectStore(rig.ctx),
    )
    assert res.status == "written"
    assert cfg.read_text() == SEED and not catalog.exists()


def test_one_shot_launch(rig, tmp_path):
    cfg = rig.home / ".codex" / "config.toml"
    spec = rig.launch_spec(PROMPT)
    assert GW_KEY not in " ".join(spec.argv) and spec.mode == "child"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name, content in spec.tmp_files.items():
        (run_dir / name).write_bytes(content)
    argv = [a.replace("@@RUN_DIR@@", str(run_dir)) for a in spec.argv]
    out = rig.run(argv, spec.env)
    assert out.returncode == 0, out.stderr
    assert "Unknown model" not in out.stderr
    assert_hit(rig)
    assert cfg.read_text() == SEED
