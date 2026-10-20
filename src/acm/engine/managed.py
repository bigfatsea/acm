"""Agents the user chose to have ACM manage (``state/managed.json``).

The file is a positive list: an agent detected later is not managed until the user selects
it. Absent file = the user has not chosen yet (callers preselect every detected agent).
"""

import json
import os
from pathlib import Path

from acm.core.context import Ctx
from acm.core.errors import IOFailureError
from acm.engine.history import WRITE_KINDS, HistoryLog


def _path(ctx: Ctx) -> Path:
    return ctx.state_dir / "managed.json"


def load_managed(ctx: Ctx) -> set[str] | None:
    """The managed agents, or None when no choice has been recorded yet."""
    try:
        data = json.loads(_path(ctx).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError:
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def save_managed(ctx: Ctx, agents: set[str]) -> None:
    p = _path(ctx)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".managed.json.acm_tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(agents), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError as e:
        raise IOFailureError(f"cannot write {p}: {e}") from e


def set_managed(ctx: Ctx, agent: str, flag: bool) -> None:
    cur = load_managed(ctx)
    # first recorded choice: start from the agents acm has actually written
    base = cur if cur is not None else {
        r.agent for r in HistoryLog(ctx).read() if r.kind in WRITE_KINDS
    }
    new = base | {agent} if flag else base - {agent}
    if new != cur:
        save_managed(ctx, new)


def is_managed_agent(ctx: Ctx, agent: str) -> bool:
    cur = load_managed(ctx)
    if cur is None:
        return any(r.kind in WRITE_KINDS for r in HistoryLog(ctx).for_agent(agent))
    return agent in cur
