import json

import pytest
from fakes import ORIGINAL, FakeAdapter, Harness, plan_of, set_

from acm.engine.apply import apply_agent
from acm.engine.history import WRITE_KINDS
from acm.engine.managed import load_managed
from acm.engine.model import Delete, Interaction
from acm.formats.base import parse


def test_first_write_records_baseline_and_keeps_user_content(h: Harness):
    h.seed()
    res = h.apply(plan_of(set_("model", "m1"), set_(("env", "A"), "1")))
    assert res.status == "written"
    text = h.text()
    assert "// my settings" in text and "// keep" in text and '"hooks": {"x": 1}' in text
    t = parse("jsonc", text.encode()).tree()
    assert t["model"] == "m1" and t["env"] == {"A": "1"} and t["theme"] == "dark"
    recs = h.log().read()
    assert [r.kind for r in recs] == ["baseline", "write"]
    base, wr = recs
    assert base.op == wr.op
    assert base.before == base.after == wr.before
    assert h.store().get(base.before) == ORIGINAL.encode()
    assert h.store().get(wr.after) == text.encode()
    assert set(wr.paths) == {("model",), ("env", "A")}
    assert wr.external_before is False


def test_second_identical_apply_is_a_noop(h: Harness):
    h.seed()
    plan = plan_of(set_("model", "m1"))
    h.apply(plan)
    n = len(h.log().read())
    res = h.apply(plan)
    assert res.status == "noop" and len(h.log().read()) == n


def test_first_takeover_needs_confirmation(ctx):
    h = Harness(ctx, FakeAdapter())
    h.seed()
    plan = plan_of(set_("model", "m1"))
    res = h.apply(plan)
    assert res.status == "blocked" and "--yes" in res.message
    assert h.text() == ORIGINAL and h.log().read() == []
    seen = []
    inter = Interaction(
        confirm_changes=lambda a, d, first: seen.append((a, first, len(d))) or False
    )
    assert h.apply(plan, inter=inter).status == "blocked"
    assert seen == [("fake", True, 1)] and h.text() == ORIGINAL
    inter = Interaction(confirm_changes=lambda a, d, first: True)
    assert h.apply(plan, inter=inter).status == "written"
    # later writes of already-managed paths need no confirmation
    res = h.apply(plan_of(set_("model", "m2")))
    assert res.status == "written"


def test_new_managed_path_needs_confirmation_again(ctx):
    h = Harness(ctx.with_flags(yes=True), FakeAdapter())
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    res = h.apply(plan_of(set_("model", "m1"), set_("extra_key", 1)), ctx=ctx)
    assert res.status == "blocked" and "confirmation" in res.message


def test_dry_run_changes_nothing(h: Harness):
    h.seed()
    res = h.apply(plan_of(set_("model", "m1")), ctx=h.ctx.with_flags(dry_run=True))
    assert res.status == "dry_run" and res.diffs
    assert h.text() == ORIGINAL and h.log().read() == []


def test_external_change_outside_managed_fields_is_not_drift(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    p = h.path
    p.write_text(
        p.read_text().replace('"theme": "dark"', '"theme": "dark", "token": "agent-wrote"')
    )
    res = h.apply(plan_of(set_("model", "m2")))
    assert res.status == "written" and not res.drift
    assert '"token": "agent-wrote"' in h.text()
    assert h.log().read()[-1].external_before is True


def test_drift_blocks_then_force_overwrites(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    h.path.write_text(h.text().replace('"m1"', '"hand-edited"'))
    res = h.apply(plan_of(set_("model", "m2")))
    assert res.status == "blocked"
    assert "hand-edited" in res.message and "m1" in res.message
    assert '"hand-edited"' in h.text()
    res = h.apply(plan_of(set_("model", "m2")), ctx=h.ctx.with_flags(force=True))
    assert res.status == "written" and '"m2"' in h.text()


@pytest.mark.parametrize(
    ("decision", "status"),
    [("overwrite", "written"), ("unmanage", "unmanaged"), ("abort", "blocked")],
)
def test_interactive_drift_choices(h: Harness, decision, status):
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    h.path.write_text(h.text().replace('"m1"', '"hand"'))
    inter = Interaction(resolve_drift=lambda a, items: decision)
    res = h.apply(plan_of(set_("model", "m2")), inter=inter)
    assert res.status == status
    assert ('"m2"' in h.text()) == (decision == "overwrite")
    assert ("fake" not in (load_managed(h.ctx) or set())) == (decision == "unmanage")


def test_removed_paths_are_retired(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1"), set_(("env", "A"), "1")))
    res = h.apply(plan_of(set_("model", "m1")))
    assert res.status == "written"
    t = parse("jsonc", h.path.read_bytes()).tree()
    assert t["env"] == {} and "A" not in t["env"]
    assert ("env", "A") in h.log().read()[-1].paths


def test_whitelist_violation_writes_nothing(h: Harness):
    h.seed()
    res = h.apply(plan_of(set_(("hooks", "x"), 2)))
    assert res.status == "blocked" and "whitelist" in res.message
    assert h.text() == ORIGINAL and h.log().read() == []


def test_unparsable_file_is_an_error_not_a_write(h: Harness):
    h.seed('{"model": ')
    res = h.apply(plan_of(set_("model", "m1")))
    assert res.status == "error"
    assert h.text() == '{"model": ' and h.log().read() == []


def test_plan_error_is_reported(h: Harness):
    from acm.engine.model import Plan

    res = h.apply(Plan(error="no default model"))
    assert res.status == "error" and "no default" in res.message


def test_new_file_gets_dash_baseline_and_baseline_restore_deletes_it(h: Harness):
    assert not h.path.exists()
    res = h.apply(plan_of(set_("model", "m1"), set_(("env", "A"), "1")))
    assert res.status == "written" and h.path.exists()
    assert h.log().baseline("fake", str(h.path)).before == "-"
    from acm.engine.restore import RestoreRequest

    res = h.restore(RestoreRequest("baseline"))
    assert res.status == "written" and not h.path.exists()
    assert "fake" not in (load_managed(h.ctx) or set())


def test_successful_write_adds_agent_back_to_managed_set(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    assert load_managed(h.ctx) == {"fake"}
    from acm.engine.restore import RestoreRequest

    h.restore(RestoreRequest("baseline"))
    assert load_managed(h.ctx) == set()
    h.apply(plan_of(set_("model", "m1")))
    assert load_managed(h.ctx) == {"fake"}


def test_takeover_of_released_agent_needs_confirmation(ctx):
    h = Harness(ctx.with_flags(yes=True), FakeAdapter())
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    from acm.engine.restore import RestoreRequest

    h.restore(RestoreRequest("baseline"))
    log = h.log()
    plan = plan_of(set_("model", "m2"))
    no_yes = h.ctx.with_flags(yes=False)
    res = apply_agent(
        no_yes, h.adapter, plan, cmd="t", op=log.new_op(), log=log, store=h.store(),
        takeover=True,
    )  # fmt: skip
    assert res.status == "blocked" and "--yes" in res.message
    assert h.text() == ORIGINAL


def test_deleting_a_user_key_via_plan_delete(h: Harness):
    h.seed()
    res = h.apply(plan_of(Delete("main", ("model",)), set_(("env", "A"), "1")))
    assert res.status == "written"
    t = parse("jsonc", h.path.read_bytes()).tree()
    assert "model" not in t and t["theme"] == "dark"
    assert any(r.kind in WRITE_KINDS for r in h.log().read())
    # the original value stays recoverable
    assert (
        json.dumps("old-model")
        in h.store().get(h.log().baseline("fake", str(h.path)).before).decode()
    )
