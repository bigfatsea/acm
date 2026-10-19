"""The active profile pointer (``state/active``)."""

import os

from acm.core.context import Ctx
from acm.core.errors import IOFailureError


def read_active(ctx: Ctx) -> str | None:
    try:
        name = (ctx.state_dir / "active").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def write_active(ctx: Ctx, name: str) -> None:
    p = ctx.state_dir / "active"
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = p.with_name(".active.acm_tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(name + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError as e:
        raise IOFailureError(f"cannot write {p}: {e}") from e
