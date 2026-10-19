"""Per-agent status (the six-state machine), derived from files + history."""

from dataclasses import dataclass, field
from typing import Literal

from acm.core.context import Ctx
from acm.core.errors import ACMError
from acm.engine.evaluate import evaluate
from acm.engine.history import WRITE_KINDS, HistoryLog, ObjectStore
from acm.engine.model import AdapterLike, Diff, DriftItem, Plan, ProjectionWarning

State = Literal["SYNCED", "OUT_OF_SYNC", "DRIFTED", "ERROR", "UNMANAGED", "NOT_DETECTED"]
SEVERITY = {
    "NOT_DETECTED": 0,
    "UNMANAGED": 0,
    "SYNCED": 0,
    "OUT_OF_SYNC": 1,
    "DRIFTED": 2,
    "ERROR": 3,
}


@dataclass
class AgentStatus:
    agent: str
    state: State
    drift: list[DriftItem] = field(default_factory=list)
    diffs: list[Diff] = field(default_factory=list)
    warnings: list[ProjectionWarning] = field(default_factory=list)
    message: str = ""
    notes: list[str] = field(default_factory=list)


def agent_status(
    ctx: Ctx,
    adapter: AdapterLike,
    plan: Plan | None,
    *,
    detected: bool,
    unmanaged: set[str],
    log: HistoryLog,
    store: ObjectStore,
) -> AgentStatus:
    if not detected:
        return AgentStatus(adapter.id, "NOT_DETECTED")
    has_records = any(r.kind in WRITE_KINDS for r in log.for_agent(adapter.id))
    if adapter.id in unmanaged or plan is None or not has_records:
        warnings = list(plan.warnings) if plan is not None else []
        return AgentStatus(adapter.id, "UNMANAGED", warnings=warnings)
    try:
        ev = evaluate(ctx, adapter, plan, log, store)
    except ACMError as e:
        return AgentStatus(adapter.id, "ERROR", message=e.message, warnings=list(plan.warnings))
    if ev.error:
        return AgentStatus(adapter.id, "ERROR", message=ev.error, warnings=list(plan.warnings))
    st = AgentStatus(
        adapter.id, "SYNCED", drift=ev.drift, diffs=ev.diffs, warnings=list(plan.warnings),
        notes=ev.notes,
    )  # fmt: skip
    if ev.drift:
        st.state = "DRIFTED"
    elif ev.changed or ev.diffs:
        st.state = "OUT_OF_SYNC"
    return st
