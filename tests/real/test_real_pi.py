import json

import pytest
from harness import GW_KEY, binary, make_rig

from acm.adapters.pi import PiFamily
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.restore import RestoreRequest, restore_agent

pytestmark = [pytest.mark.real, pytest.mark.skipif(binary("pi") is None, reason="pi not installed")]

MODELS = {
    "providers": {
        "ollama": {
            "baseUrl": "http://localhost:11434/v1",
            "api": "openai-completions",
            "apiKey": "ollama",
            "models": [{"id": "llama3.1:8b"}],
        }
    }
}
SETTINGS = {"defaultProvider": "ollama", "defaultModel": "llama3.1:8b", "theme": "dark"}
PROMPT = ["-p", "reply with OK"]
ENV = {"PI_OFFLINE": "1"}


@pytest.fixture
def rig(tmp_path):
    r = make_rig(tmp_path, PiFamily())
    d = r.home / ".pi" / "agent"
    d.mkdir(parents=True)
    (d / "models.json").write_text(json.dumps(MODELS, indent=2) + "\n")
    (d / "settings.json").write_text(json.dumps(SETTINGS, indent=2) + "\n")
    yield r
    r.gateway.stop()


def assert_hit(rig, suffix, model="coding"):
    posts = rig.inference_posts(suffix)
    assert posts, f"no request reached the gateway: {rig.gateway.requests}"
    assert posts[0]["body"]["model"] == model
    h = posts[0]["headers"]
    assert GW_KEY in (h.get("authorization", "") + h.get("x-api-key", ""))


def test_persistent_projection_reaches_the_gateway(rig):
    rig.project()
    out = rig.run([rig.adapter.find_bin(rig.ctx), *PROMPT], ENV)
    assert out.returncode == 0, out.stderr + out.stdout
    assert "OK" in out.stdout
    assert_hit(rig, "/chat/completions")
    d = rig.home / ".pi" / "agent"
    models = json.loads((d / "models.json").read_text())
    assert "ollama" in models["providers"] and "vmr" in models["providers"]
    assert models["providers"]["vmr"]["apiKey"] == "$VMR_KEY"
    settings = json.loads((d / "settings.json").read_text())
    assert settings["theme"] == "dark" and settings["defaultProvider"] == "vmr"
    assert GW_KEY not in (d / "models.json").read_text()


def test_baseline_restore(rig):
    d = rig.home / ".pi" / "agent"
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    rig.project()
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
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before


def test_one_shot_launch_via_extension(rig):
    d = rig.home / ".pi" / "agent"
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    spec = rig.launch_spec(PROMPT)
    assert GW_KEY not in " ".join(spec.argv) and GW_KEY not in json.dumps(spec.env)
    out = rig.run(spec.argv, {**spec.env, **ENV})
    assert out.returncode == 0, out.stderr + out.stdout
    assert_hit(rig, "/chat/completions")
    # Pi creates its own runtime files (auth.json...); acm's two files must be untouched
    for name in ("models.json", "settings.json"):
        assert (d / name).read_bytes() == before[name]
    assert not rig.ctx.history_path.exists()
