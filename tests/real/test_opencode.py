import json

import pytest
from harness import GW_KEY, binary, make_rig

from acm.adapters.opencode import OpenCodeFamily
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.restore import RestoreRequest, restore_agent

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(binary("opencode") is None, reason="opencode not installed"),
]

SEED = """{
  // my opencode
  "$schema": "https://opencode.ai/config.json",
  "theme": "tokyonight",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {"baseURL": "http://127.0.0.1:11434/v1"},
      "models": {"qwen3-coder:a3b": {"name": "Qwen3 Coder", "limit": {"context": 128000, "output": 8192}}}
    }
  },
  "model": "ollama/qwen3-coder:a3b"
}
"""
PROMPT = ["run", "reply with OK"]
ENV = {"OPENCODE_DISABLE_AUTOUPDATE": "1"}


@pytest.fixture
def rig(tmp_path):
    r = make_rig(tmp_path, OpenCodeFamily())
    cfg = r.home / ".config" / "opencode" / "opencode.jsonc"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(SEED)
    r.env.update(ENV)
    yield r
    r.gateway.stop()


def assert_hit(rig, model="coding"):
    posts = rig.inference_posts("/chat/completions")
    assert posts, f"no request reached the gateway: {rig.gateway.requests}"
    models = {p["body"]["model"] for p in posts}
    assert model in models, models
    assert all(p["headers"]["authorization"] == f"Bearer {GW_KEY}" for p in posts)
    return models


def test_persistent_projection_reaches_the_gateway(rig):
    rig.project()
    out = rig.run([rig.adapter.find_bin(rig.ctx), *PROMPT])
    assert out.returncode == 0, out.stderr + out.stdout
    assert "OK" in out.stdout
    # the main model answered, and OpenCode used small_model (our `fast` role) for its title
    assert assert_hit(rig) == {"coding", "cheap"}
    path = rig.home / ".config" / "opencode" / "opencode.jsonc"
    text = path.read_text()
    assert "// my opencode" in text and '"theme": "tokyonight"' in text
    assert "{env:VMR_KEY}" in text and GW_KEY not in text


def test_baseline_restore_gives_back_the_original_bytes(rig):
    path = rig.home / ".config" / "opencode" / "opencode.jsonc"
    rig.project()
    assert path.read_text() != SEED
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
    assert path.read_text() == SEED


def test_one_shot_launch_via_inline_config(rig):
    path = rig.home / ".config" / "opencode" / "opencode.jsonc"
    spec = rig.launch_spec(PROMPT)
    assert GW_KEY not in " ".join(spec.argv) + json.dumps(spec.env)
    out = rig.run(spec.argv, spec.env)
    assert out.returncode == 0, out.stderr + out.stdout
    assert_hit(rig)
    assert path.read_text() == SEED and not rig.ctx.history_path.exists()
