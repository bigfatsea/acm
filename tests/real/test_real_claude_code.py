import json

import pytest
from harness import GW_KEY, binary, make_rig

from acm.adapters.claude_code import ClaudeCode
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.restore import RestoreRequest, restore_agent

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(binary("claude") is None, reason="claude not installed"),
]

SEED = {
    "env": {"ANTHROPIC_API_KEY": "sk-ant-REAL-USER-KEY", "DISABLE_TELEMETRY": "1"},
    "permissions": {"allow": ["Bash(git status)"]},
    "includeCoAuthoredBy": False,
}
PROMPT = ["-p", "reply with OK", "--output-format", "json"]


@pytest.fixture
def rig(tmp_path):
    r = make_rig(tmp_path, ClaudeCode())
    r.gateway.reply_text = "OK"
    settings = r.home / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps(SEED, indent=2) + "\n")
    yield r
    r.gateway.stop()


def assert_hit(rig, model="claude"):
    posts = rig.inference_posts("/v1/messages")
    assert posts, f"no request reached the gateway: {rig.gateway.requests}"
    p = posts[0]
    assert p["body"]["model"] == model
    assert (
        p["headers"].get("x-api-key") == GW_KEY
        or p["headers"].get("authorization") == f"Bearer {GW_KEY}"
    )
    assert "sk-ant-REAL-USER-KEY" not in json.dumps(p["headers"])


def test_persistent_projection_reaches_the_gateway(rig):
    rig.project()
    out = rig.run([rig.adapter.find_bin(rig.ctx), *PROMPT])
    assert out.returncode == 0, out.stderr
    assert "OK" in out.stdout
    assert_hit(rig)
    saved = json.loads((rig.home / ".claude" / "settings.json").read_text())
    assert saved["permissions"] == SEED["permissions"] and saved["env"]["DISABLE_TELEMETRY"] == "1"
    assert "ANTHROPIC_API_KEY" not in saved["env"]
    assert GW_KEY not in json.dumps(saved)  # the key is referenced via apiKeyHelper, not written


def test_baseline_restore_gives_the_original_file_back(rig):
    path = rig.home / ".claude" / "settings.json"
    original = path.read_bytes()
    rig.project()
    assert path.read_bytes() != original
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
    assert json.loads(path.read_text()) == SEED


def test_one_shot_launch_reaches_the_gateway_and_writes_nothing(rig):
    path = rig.home / ".claude" / "settings.json"
    before = path.read_bytes()
    spec = rig.launch_spec(PROMPT)
    assert GW_KEY not in " ".join(spec.argv)
    out = rig.run(spec.argv, spec.env)
    assert out.returncode == 0, out.stderr
    assert_hit(rig)
    assert path.read_bytes() == before
    assert not rig.ctx.history_path.exists()
