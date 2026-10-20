from fakes import Harness, plan_of, set_

from acm.engine.managed import set_managed
from acm.engine.model import Plan
from acm.engine.restore import RestoreRequest
from acm.engine.status import agent_status
from acm.engine.views import guess_format, prune, record_changes
from acm.formats.base import MISSING


def status(h: Harness, plan, *, detected=True):
    from acm.engine.managed import load_managed

    return agent_status(
        h.ctx, h.adapter, plan, detected=detected, managed=load_managed(h.ctx),
        log=h.log(), store=h.store(),
    )  # fmt: skip


def test_state_machine(h: Harness):
    h.seed()
    plan = plan_of(set_("model", "m1"))
    assert status(h, plan, detected=False).state == "NOT_DETECTED"
    assert status(h, plan).state == "UNMANAGED"  # never applied
    h.apply(plan)
    assert status(h, plan).state == "SYNCED"
    s = status(h, plan_of(set_("model", "m2")))
    assert s.state == "OUT_OF_SYNC" and s.diffs[0].desired == "m2"
    h.path.write_text(h.text().replace('"m1"', '"hand"'))
    s = status(h, plan)
    assert s.state == "DRIFTED" and s.drift[0].found == "hand"
    h.path.write_text('{"model": ')
    assert status(h, plan).state == "ERROR"
    assert status(h, Plan(error="boom")).state == "ERROR"


def test_unmanaged_flag_and_missing_plan(h: Harness):
    h.seed()
    plan = plan_of(set_("model", "m1"))
    h.apply(plan)
    assert status(h, None).state == "UNMANAGED"
    set_managed(h.ctx, "fake", False)
    assert status(h, plan).state == "UNMANAGED"


def test_whitelist_problem_surfaces_as_error_state(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    assert status(h, plan_of(set_(("hooks", "x"), 1))).state == "ERROR"


def test_record_changes_lists_field_values(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1"), set_(("env", "A"), "1")))
    h.apply(plan_of(set_("model", "m2")))
    recs = [r for r in h.log().read() if r.kind == "write"]
    first = {c.path: (c.before, c.after) for c in record_changes(h.store(), recs[0])}
    assert first[("model",)] == ("old-model", "m1") and first[("env", "A")] == (MISSING, "1")
    second = {c.path: (c.before, c.after) for c in record_changes(h.store(), recs[1])}
    assert second[("model",)] == ("m1", "m2") and second[("env", "A")] == ("1", MISSING)
    assert guess_format("/x/a.yml") == "yaml" and guess_format("/x/a") is None


def test_prune_keeps_baseline_and_newest_and_folds_paths(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1"), set_(("env", "A"), "1")))
    h.apply(plan_of(set_("model", "m2")))
    h.apply(plan_of(set_("model", "m3")))
    removed, objs = prune(h.ctx, keep=1)
    assert removed == 2 and objs >= 1
    recs = h.log().read()
    assert [r.kind for r in recs] == ["baseline", "write"]
    # a baseline restore still knows about env.A (path was folded into the baseline record)
    h.restore(RestoreRequest("baseline"))
    from acm.formats.base import parse

    t = parse("jsonc", h.path.read_bytes()).tree()
    assert "env" not in t and t["model"] == "old-model"
    assert prune(h.ctx, keep=5) == (0, 0)
