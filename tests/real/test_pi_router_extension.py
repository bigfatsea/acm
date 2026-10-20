"""The `acm/auto` router inside the bundled Pi extension, driven by node with a stub `pi`.

Only follow-ups, retries and background requests are checked here: a real `pi -p` run makes
one user request, which test_real_pi.py covers per thinking level."""

import json
import subprocess
from importlib import resources

import pytest
from harness import binary

pytestmark = [pytest.mark.real, pytest.mark.skipif(binary("node") is None, reason="node missing")]

DRIVER = r"""
const ext = (await import(process.argv[2])).default;
let vm;
const models = {};
ext({
  registerProvider(alias, cfg) {
    for (const m of cfg.models) models[`${alias}/${m.id}`] = { provider: alias, ...m };
  },
  registerVirtualModel(def) { vm = def; },
});
const ctx = { modelRegistry: { find: (p, id) => models[`${p}/${id}`] } };
const pick = (r) => { const out = vm.route(r, ctx); return [out.model.id, out.thinkingLevel]; };
const deep = { model: models["vmr/deep"], thinkingLevel: "high" };
console.log(JSON.stringify({
  levels: vm.thinkingLevels,
  user_low: pick({ reason: "user", thinkingLevel: "low" }),
  user_unknown_level: pick({ reason: "user", thinkingLevel: "xhigh" }),
  continuation_stays: pick({ reason: "continuation", thinkingLevel: "low", previous: deep }),
  retry_stays: pick({ reason: "retry", thinkingLevel: "low", failed: deep }),
  direct_fast_fits: pick({ reason: "direct", previous: { model: models["vmr/main"] } }),
  direct_fast_too_small: pick({ reason: "direct", previous: deep }),
}));
"""


def test_router_keeps_follow_ups_and_guards_background_windows(tmp_path):
    providers = [{"alias": "vmr", "name": "vmr", "baseUrl": "http://x/v1", "apiKey": "$K",
                  "api": "openai-completions", "models": [
                      {"id": "quick", "contextWindow": 200000},
                      {"id": "main", "contextWindow": 200000},
                      {"id": "deep", "contextWindow": 1000000}]}]  # fmt: skip
    tier = lambda m, t, c: {"provider": "vmr", "model": m, "thinking": t, "context": c}  # noqa: E731
    router = {"tiers": {"low": tier("quick", "low", 200000), "medium": tier("main", "medium", 200000),
                        "high": tier("deep", "high", 1000000)}, "contextWindow": 200000}  # fmt: skip
    (tmp_path / "driver.mjs").write_text(DRIVER)
    ext = str(resources.files("acm.adapters").joinpath("data/acm_pi_provider.ts"))
    env = {"PATH": __import__("os").environ["REAL_PATH"], "ACM_PI_PROVIDERS": json.dumps(providers),
           "ACM_PI_ROUTER": json.dumps(router)}  # fmt: skip
    out = subprocess.run([binary("node"), str(tmp_path / "driver.mjs"), ext], env=env,
                         capture_output=True, text=True, timeout=60)  # fmt: skip
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["levels"] == ["low", "medium", "high"]
    assert got["user_low"] == ["quick", "low"]
    assert got["user_unknown_level"] == ["main", "medium"]  # anything else: the default model
    assert got["continuation_stays"] == ["deep", "high"]
    assert got["retry_stays"] == ["deep", "high"]
    assert got["direct_fast_fits"] == ["quick", "low"]
    assert got["direct_fast_too_small"] == ["deep", "high"]  # 200k cannot summarise 1M
