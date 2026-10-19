"""Agents the user chose not to have ACM manage (``state/unmanaged.json``)."""

import json
import os
from pathlib import Path

from acm.core.context import Ctx
from acm.core.errors import IOFailureError


def _path(ctx: Ctx) -> Path:
    return ctx.state_dir / "unmanaged.json"


def load_unmanaged(ctx: Ctx) -> set[str]:
    try:
        data = json.loads(_path(ctx).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def set_unmanaged(ctx: Ctx, agent: str, flag: bool) -> None:
    cur = load_unmanaged(ctx)
    new = cur | {agent} if flag else cur - {agent}
    if new == cur:
        return
    p = _path(ctx)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".unmanaged.json.acm_tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(new), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError as e:
        raise IOFailureError(f"cannot write {p}: {e}") from e
