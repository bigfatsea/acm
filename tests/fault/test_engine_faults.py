import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fakes import FakeAdapter, Harness, plan_of, set_

from acm.core.context import Ctx
from acm.core.errors import SafetyBlockedError
from acm.engine.commit import FileChange, commit
from acm.engine.fsio import atomic_write
from acm.engine.history import HistoryLog, Record

pytestmark = pytest.mark.fault
ORIGINAL = '{\n  "model": "old"\n}\n'


def harness(ctx: Ctx, **kw):
    return Harness(ctx.with_flags(yes=True), FakeAdapter(**kw))


def test_midway_failure_reverts_every_written_file(ctx):
    env = {**ctx.env, "ACM_TEST_FAULT_AFTER_FIRST_FILE": "1"}
    h = harness(Ctx.from_env(env, interactive=False), extra=True)
    h.seed(ORIGINAL)
    extra = h.adapter.path(h.ctx, "extra")
    extra.write_text('title = "x"\n')
    plan = plan_of(set_("model", "new"), set_("extra_key", 1, file="extra"))
    res = h.apply(plan)
    assert (res.status == "error" and "rolled back" in res.message) or "injected" in res.message
    assert h.text() == ORIGINAL
    assert extra.read_text() == 'title = "x"\n'
    assert [r.kind for r in h.log().read()] == ["baseline", "baseline"]  # no write record


def test_failure_after_objects_leaves_files_untouched(ctx):
    env = {**ctx.env, "ACM_TEST_FAULT_AFTER_OBJECTS": "1"}
    h = harness(Ctx.from_env(env, interactive=False))
    h.seed(ORIGINAL)
    assert h.apply(plan_of(set_("model", "new"))).status == "error"
    assert h.text() == ORIGINAL


def test_sigkill_between_file_write_and_history_record(ctx, tmp_path):
    """The baseline is recorded first, so even a killed process never loses the original."""
    h = harness(ctx)
    h.seed(ORIGINAL)
    script = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from fakes import FakeAdapter, Harness, plan_of, set_
        from acm.core.context import Ctx
        from acm.engine.apply import apply_agent
        from acm.engine.history import HistoryLog, ObjectStore
        ctx = Ctx.from_env(dict(os.environ), interactive=False, yes=True)
        log = HistoryLog(ctx)
        apply_agent(ctx, FakeAdapter(), plan_of(set_("model", "new")), cmd="x",
                    op=log.new_op(), log=log, store=ObjectStore(ctx))
        """
    )
    env = {
        **ctx.env,
        "ACM_TEST_FAULT_BEFORE_RECORD": "1",
        "ACM_TEST_FAULT_MODE": "kill",
        "PYTHONPATH": os.pathsep.join([str(Path(__file__).resolve().parents[1]), *sys.path]),
    }
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
    assert proc.returncode == 137, proc.stderr
    assert '"new"' in h.text()  # the file was replaced
    kinds = [r.kind for r in h.log().read()]
    assert kinds == ["baseline"]  # but the write was never recorded
    base = h.log().baseline("fake", str(h.path))
    assert h.store().get(base.before) == ORIGINAL.encode()
    # the next run treats it as a fresh takeover and everything still works
    res = h.apply(plan_of(set_("model", "newer")))
    assert res.status == "written"
    from acm.engine.restore import RestoreRequest

    h.restore(RestoreRequest("baseline", whole_file=True))
    assert h.text() == ORIGINAL


def test_file_changed_between_plan_and_commit_is_detected(ctx):
    h = harness(ctx)
    h.seed(ORIGINAL)
    spec = h.adapter.files(h.ctx)[0]
    stale = FileChange(spec, ORIGINAL.encode(), b'{"model": "x"}\n', (("model",),))
    h.path.write_text('{"model": "changed by agent"}\n')
    with pytest.raises(SafetyBlockedError, match="changed while acm"):
        commit(h.ctx, "fake", [stale], op=1, kind="write", cmd="x", log=h.log(), store=h.store())
    assert "changed by agent" in h.text() and h.log().read() == []


def test_history_with_truncated_last_line_is_tolerated(ctx):
    h = harness(ctx)
    h.seed(ORIGINAL)
    h.apply(plan_of(set_("model", "m1")))
    p = ctx.history_path
    p.write_bytes(p.read_bytes() + b'{"v":1,"seq":99,"tim')
    log = HistoryLog(ctx)
    assert [r.kind for r in log.read()] == ["baseline", "write"]
    assert any("last line" in w for w in log.warnings)
    log.append(
        Record(
            seq=3,
            time="t",
            op=9,
            agent="fake",
            file="f",
            kind="write",
            cmd="",
            before="-",
            after="-",
            paths=(),
        )
    )
    again = HistoryLog(ctx).read()
    assert len(again) == 3 and again[-1].op == 9  # appended on its own line


def test_garbage_line_in_the_middle_is_skipped_with_warning(ctx):
    h = harness(ctx)
    h.seed(ORIGINAL)
    h.apply(plan_of(set_("model", "m1")))
    lines = ctx.history_path.read_text().splitlines()
    ctx.history_path.write_text(lines[0] + "\nnot json\n" + lines[1] + "\n")
    log = HistoryLog(ctx)
    assert len(log.read()) == 2 and any("line 2" in w for w in log.warnings)


def test_missing_object_during_drift_check_is_a_note_not_a_crash(ctx):
    h = harness(ctx)
    h.seed(ORIGINAL)
    h.apply(plan_of(set_("model", "m1")))
    rec = h.log().last_write("fake", str(h.path))
    (ctx.objects_dir / rec.after[:2] / rec.after).unlink()
    from acm.engine.evaluate import evaluate

    ev = evaluate(h.ctx, h.adapter, plan_of(set_("model", "m2")), h.log(), h.store())
    assert ev.drift == [] and any("cannot verify drift" in n for n in ev.notes)


def test_lock_contention_across_processes(ctx):
    from acm.core.lock import WriteLock

    code = textwrap.dedent(
        """
        import os, sys, time
        from acm.core.context import Ctx
        from acm.core.lock import WriteLock
        ctx = Ctx.from_env(dict(os.environ), interactive=False)
        with WriteLock(ctx):
            print("locked", flush=True)
            time.sleep(30)
        """
    )
    p = subprocess.Popen(
        [sys.executable, "-c", code], env=dict(ctx.env), stdout=subprocess.PIPE, text=True
    )
    try:
        assert p.stdout.readline().strip() == "locked"
        with pytest.raises(SafetyBlockedError):
            WriteLock(ctx).acquire()
    finally:
        p.kill()
        p.wait()
    with WriteLock(ctx):  # released when the holder died
        pass


def test_symlinked_config_keeps_the_link_and_mode(tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text("{}\n")
    os.chmod(real, 0o640)
    link = tmp_path / "linked" / "settings.json"
    link.parent.mkdir()
    link.symlink_to(real)
    atomic_write(link, b'{"a": 1}\n')
    assert link.is_symlink() and real.read_bytes() == b'{"a": 1}\n'
    assert oct(real.stat().st_mode & 0o777) == "0o640"


def test_hardlinked_file_is_rewritten_in_place(tmp_path):
    a = tmp_path / "a.json"
    a.write_text("{}\n")
    b = tmp_path / "b.json"
    os.link(a, b)
    atomic_write(a, b'{"x": 1}\n')
    assert b.read_bytes() == b'{"x": 1}\n' and a.stat().st_ino == b.stat().st_ino


def test_new_files_are_private_and_no_temp_files_remain(tmp_path):
    p = tmp_path / "d" / "new.json"
    atomic_write(p, b"{}\n")
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert [x.name for x in p.parent.iterdir()] == ["new.json"]


def test_state_files_are_private(ctx):
    h = harness(ctx)
    h.seed(ORIGINAL)
    h.apply(plan_of(set_("model", "m1")))
    assert oct(ctx.history_path.stat().st_mode & 0o777) == "0o600"
    for p in ctx.objects_dir.rglob("*"):
        if p.is_file():
            assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert json.loads(ctx.history_path.read_text().splitlines()[0])["v"] == 1
