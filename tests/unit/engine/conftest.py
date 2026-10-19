import pytest
from fakes import ORIGINAL, FakeAdapter, Harness

from acm.core.context import Ctx

__all__ = ["ORIGINAL", "Harness"]


@pytest.fixture
def yes_ctx(ctx: Ctx) -> Ctx:
    return ctx.with_flags(yes=True)


@pytest.fixture
def h(yes_ctx: Ctx) -> Harness:
    return Harness(yes_ctx, FakeAdapter())
