"""Test doubles for the engine: a configurable fake adapter."""

from collections.abc import Iterable
from pathlib import Path

from acm.core.context import Ctx
from acm.engine.apply import apply_agent
from acm.engine.history import HistoryLog, ObjectStore
from acm.engine.model import ApplyResult, Delete, FileSpec, Interaction, OwnedFile, Plan, Set
from acm.engine.restore import RestoreRequest, restore_agent
from acm.formats.base import KeyPath


class FakeAdapter:
    """Two shared files (json ``main``, toml ``extra``) and one owned file (``catalog``)."""

    id = "fake"
    name = "Fake Agent"

    def __init__(
        self,
        *,
        main_fmt: str = "jsonc",
        extra: bool = False,
        owned: bool = False,
        managed: Iterable[KeyPath] = (("model",), ("env",), ("providers",), ("extra_key",)),
    ) -> None:
        self.main_fmt = main_fmt
        self.with_extra = extra
        self.with_owned = owned
        self.managed = [tuple(m) for m in managed]

    def files(self, ctx: Ctx) -> list[FileSpec]:
        base = ctx.home / ".fake"
        specs = [FileSpec("main", base / f"settings.{self.main_fmt}", self.main_fmt)]
        if self.with_extra:
            specs.append(FileSpec("extra", base / "config.toml", "toml"))
        if self.with_owned:
            specs.append(
                FileSpec("catalog", ctx.acm_home / "owned" / "fake" / "catalog.json", "json", True)
            )
        return specs

    def is_managed(self, logical: str, path: KeyPath) -> bool:
        if logical == "main":
            return any(path[: len(m)] == m for m in self.managed)
        if logical == "extra":
            return path[:1] == ("extra_key",)
        return False

    def path(self, ctx: Ctx, logical: str = "main") -> Path:
        return next(s.path for s in self.files(ctx) if s.logical == logical)


def plan_of(*ops: Set | Delete | OwnedFile) -> Plan:
    return Plan(ops=list(ops))


def set_(path: KeyPath | str, value: object, file: str = "main") -> Set:
    p = (path,) if isinstance(path, str) else path
    return Set(file, p, value)


ORIGINAL = """\
{
  // my settings
  "theme": "dark", // keep
  "hooks": {"x": 1},
  "model": "old-model"
}
"""


class Harness:
    def __init__(self, ctx: Ctx, adapter: FakeAdapter) -> None:
        self.ctx = ctx
        self.adapter = adapter

    @property
    def path(self) -> Path:
        return self.adapter.path(self.ctx)

    def seed(self, text: str = ORIGINAL) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def log(self) -> HistoryLog:
        return HistoryLog(self.ctx)

    def store(self) -> ObjectStore:
        return ObjectStore(self.ctx)

    def apply(
        self, plan: Plan, *, ctx: Ctx | None = None, inter: Interaction | None = None
    ) -> ApplyResult:
        c = ctx or self.ctx
        log = self.log()
        return apply_agent(
            c, self.adapter, plan, cmd="acm use t", op=log.new_op(), log=log,
            store=self.store(), interaction=inter,
        )  # fmt: skip

    def restore(
        self, req: RestoreRequest, *, ctx: Ctx | None = None, inter: Interaction | None = None
    ) -> ApplyResult:
        c = ctx or self.ctx
        log = self.log()
        return restore_agent(
            c, self.adapter, req, cmd="acm restore", op=log.new_op(), log=log,
            store=self.store(), interaction=inter,
        )  # fmt: skip
