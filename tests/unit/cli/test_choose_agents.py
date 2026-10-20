import pytest

from acm.adapters.registry import all_adapters
from acm.cli.output import Out
from acm.cli.support import choose_agents
from acm.core.errors import SafetyBlockedError


def _run(monkeypatch, answers: list[str], pre: set[str]) -> list[str]:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(it))
    agents = all_adapters()[:3]
    return [a.id for a in choose_agents(Out(no_color=True), agents, pre)]


def test_preselected_agents_are_chosen_on_enter(monkeypatch):
    ids = [a.id for a in all_adapters()[:3]]
    assert _run(monkeypatch, [""], {ids[1]}) == [ids[1]]


def test_toggle_all_none(monkeypatch):
    ids = [a.id for a in all_adapters()[:3]]
    assert _run(monkeypatch, ["1 3", ""], {ids[1]}) == ids
    assert _run(monkeypatch, ["a", ""], set()) == ids
    assert _run(monkeypatch, ["n", ""], set(ids)) == []
    assert _run(monkeypatch, ["9 x", ""], {ids[0]}) == [ids[0]]  # junk is ignored


def test_quit_aborts(monkeypatch):
    with pytest.raises(SafetyBlockedError):
        _run(monkeypatch, ["q"], set())
