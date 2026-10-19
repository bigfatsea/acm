import pytest
from fakes import ORIGINAL, FakeAdapter, Harness, plan_of, set_

from acm.core.errors import NotFoundError
from acm.engine.model import Interaction
from acm.engine.restore import RestoreRequest
from acm.formats.base import parse


def tree(h: Harness):
    return parse("jsonc", h.path.read_bytes()).tree()


def two_ops(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1"), set_(("env", "A"), "1")))
    h.apply(plan_of(set_("model", "m2"), set_(("env", "B"), "2")))


def test_rollback_restores_managed_fields_and_keeps_later_agent_state(h: Harness):
    two_ops(h)
    h.path.write_text(h.text().replace('"theme": "dark"', '"theme": "dark", "late": 1'))
    res = h.restore(RestoreRequest("rollback"))
    assert res.status == "written"
    t = tree(h)
    assert t["model"] == "m1" and t["env"] == {"A": "1"} and t["late"] == 1
    assert "// my settings" in h.text()


def test_rollback_can_itself_be_rolled_back(h: Harness):
    two_ops(h)
    before = h.text()
    h.restore(RestoreRequest("rollback"))
    assert tree(h)["model"] == "m1"
    h.restore(RestoreRequest("rollback"))
    assert h.text() == before


def test_restore_specific_op(h: Harness):
    two_ops(h)
    ops = sorted({r.op for r in h.log().read() if r.kind == "write"})
    h.restore(RestoreRequest("op", op=ops[0]))
    t = tree(h)
    assert t["model"] == "m1" and t["env"] == {"A": "1"}
    assert t["theme"] == "dark" and t["hooks"] == {"x": 1}


def test_restore_unknown_op(h: Harness):
    two_ops(h)
    with pytest.raises(NotFoundError):
        h.restore(RestoreRequest("op", op=999))


def test_restore_baseline_returns_to_pre_acm_values_and_prunes_created_objects(h: Harness):
    two_ops(h)
    res = h.restore(RestoreRequest("baseline"))
    assert res.status == "written"
    assert h.text() == ORIGINAL  # byte-identical: edits were pure insert/replace


def test_baseline_keeps_user_changes_made_after_takeover(h: Harness):
    two_ops(h)
    h.path.write_text(h.text().replace('"theme": "dark"', '"theme": "light"'))
    h.restore(RestoreRequest("baseline"))
    t = tree(h)
    assert t["theme"] == "light" and t["model"] == "old-model" and "env" not in t


def test_whole_file_restore_requires_confirmation_when_it_discards_changes(h: Harness):
    two_ops(h)
    ctx_no = h.ctx.with_flags(yes=False)
    h.path.write_text(h.text().replace('"theme": "dark"', '"theme": "light"'))
    req = RestoreRequest("baseline", whole_file=True)
    res = h.restore(req, ctx=ctx_no)
    assert res.status == "blocked" and "discard" in res.message and "theme" in res.message
    seen = []
    inter = Interaction(confirm_file_restore=lambda a, ps: seen.append(ps) or False)
    assert h.restore(req, ctx=ctx_no, inter=inter).status == "blocked" and seen
    inter = Interaction(confirm_file_restore=lambda a, ps: True)
    assert h.restore(req, ctx=ctx_no, inter=inter).status == "written"
    assert h.text() == ORIGINAL


def test_whole_file_restore_then_undo(h: Harness):
    two_ops(h)
    pre = h.text()
    h.restore(RestoreRequest("baseline", whole_file=True))
    assert h.text() == ORIGINAL
    h.restore(RestoreRequest("rollback", whole_file=True))
    assert h.text() == pre


def test_restore_dry_run(h: Harness):
    two_ops(h)
    pre = h.text()
    res = h.restore(RestoreRequest("baseline"), ctx=h.ctx.with_flags(dry_run=True))
    assert res.status == "dry_run" and res.diffs and h.text() == pre


def test_restore_noop_when_already_there(h: Harness):
    h.seed()
    h.apply(plan_of(set_("model", "m1")))
    h.restore(RestoreRequest("rollback"))
    n = len(h.log().read())
    res = h.restore(RestoreRequest("baseline"))
    assert res.status == "noop" and len(h.log().read()) == n


def test_restore_without_history_is_not_found(h: Harness):
    h.seed()
    with pytest.raises(NotFoundError):
        h.restore(RestoreRequest("rollback"))


def test_restore_records_a_restore_entry_and_updates_drift_basis(h: Harness):
    two_ops(h)
    h.restore(RestoreRequest("rollback"))
    last = h.log().read()[-1]
    assert last.kind == "restore" and set(last.paths) >= {("model",), ("env", "A"), ("env", "B")}
    # after a restore the restored values are the new "what acm wrote": no drift
    from acm.engine.evaluate import evaluate

    ev = evaluate(
        h.ctx, h.adapter, plan_of(set_("model", "m1"), set_(("env", "A"), "1")), h.log(), h.store()
    )
    assert ev.drift == []


def test_restore_refuses_corrupt_or_missing_versions(h: Harness):
    two_ops(h)
    rec = [r for r in h.log().read() if r.kind == "write"][-1]
    obj = h.ctx.objects_dir / rec.before[:2] / rec.before
    obj.write_bytes(b"tampered")
    res = h.restore(RestoreRequest("rollback"))
    assert res.status == "error" and "corrupt" in res.message
    obj.unlink()
    res = h.restore(RestoreRequest("rollback"))
    assert res.status == "error" and "missing" in res.message


def test_owned_file_lifecycle(ctx):
    h = Harness(ctx.with_flags(yes=True), FakeAdapter(owned=True))
    from acm.engine.model import OwnedFile

    cat = h.adapter.path(h.ctx, "catalog")
    h.seed()
    res = h.apply(plan_of(set_("model", "m1"), OwnedFile("catalog", b'{"models": []}\n')))
    assert res.status == "written" and cat.read_bytes() == b'{"models": []}\n'
    cat.write_bytes(b"{}")
    res = h.apply(plan_of(set_("model", "m1"), OwnedFile("catalog", b'{"models": []}\n')))
    assert res.status == "blocked" and "catalog.json" in res.message
    h.restore(RestoreRequest("baseline"))
    assert not cat.exists()
    assert h.text() == ORIGINAL


def test_retired_owned_file_is_removed(ctx):
    h = Harness(ctx.with_flags(yes=True), FakeAdapter(owned=True))
    from acm.engine.model import OwnedFile

    h.seed()
    h.apply(plan_of(set_("model", "m1"), OwnedFile("catalog", b"{}\n")))
    cat = h.adapter.path(h.ctx, "catalog")
    assert cat.exists()
    h.apply(plan_of(set_("model", "m1")))
    assert not cat.exists()
