"""Help is a deterministic, private read without advancing or leaving an activity."""

import copy

import pytest
from pydantic import ValidationError

from core.environment.rejection import Rejected
from core.interaction import Card, EventKind
from tests.runtime.activities import test_engine as activities
from tests.runtime.realtime import test_engine as realtime

engine = activities.engine
rt = realtime.rt


def enter(gate, kind):
    if kind == "work":
        activities.work(gate)
    elif kind == "conversation":
        activities.conversation(gate)
    elif kind == "rest":
        gate.select("Mei", activities.choose("select_rest", arguments={"until": "09:00"}))
    elif kind == "move":
        gate.select("Mei", activities.choose("select_move", target="workshop"))


@pytest.mark.parametrize("fixture", ["engine", "rt"])
@pytest.mark.parametrize("kind", ["selection", "work", "conversation", "rest", "move"])
def test_help_exists_in_every_activity_and_preserves_state(request, fixture, kind):
    gate = request.getfixturevalue(fixture)
    enter(gate, kind)
    card = Card(gate.observation("Mei").allowed)
    reply = card.model.model_validate({"thought": "Read the rules", "do": "help"})
    action = card.decision(reply).action
    assert action.tool == "help" and not action.arguments
    gate.emit(EventKind.ACTIVITY_FEEDBACK, "Unread before help", actor="Mei")
    unread = {e.seq for e in gate.env.log.pending_events("Mei")}
    now, current = gate.now, dict(gate.current)
    queue = copy.deepcopy(gate.queue.events)
    members = {key: copy.deepcopy(a.members) for key, a in gate.activities.items()}
    text = gate.schedule("Mei", action)
    assert "Activity help" in text
    assert '"do": "help"' in text
    assert gate.now == now and gate.current == current and gate.queue.events == queue
    assert {key: a.members for key, a in gate.activities.items()} == members
    assert unread <= {e.seq for e in gate.env.log.pending_events("Mei")}
    assert not gate.pending
    if fixture == "rt":
        assert not gate.running
        assert "You hear completed speech directly" in text
    if kind == "conversation":
        assert '"do": "submit your repair"' not in text
    if kind in ("rest", "move"):
        with pytest.raises(ValidationError):
            card.model.model_validate({"thought": "Cancel", "do": "pause or leave"})
    events = activities.events(gate)
    help_events = [e for e in events if e["payload"].get("tool") == "help"]
    assert [e["kind"] for e in help_events] == ["tool_started", "tool_completed"]
    assert all(e["audience"] == ["Mei"] for e in help_events)


async def test_work_help_includes_public_repository_guide_without_running_code(rt, monkeypatch):
    activities.work(rt)
    await realtime.take(rt)
    provider = next(iter(rt.env.providers.values()))
    monkeypatch.setattr(
        provider, "work_guide", lambda part: "PUBLIC REPOSITORY GUIDE", raising=False
    )
    observation = rt.observation("Mei")
    assert "PUBLIC REPOSITORY GUIDE" not in observation.situation
    assert "repository work guide" in observation.setting
    assert "guide" in rt.menu("Mei")["tools"]
    assert "task-1" in observation.situation
    text = rt.schedule("Mei", activities.use("help"))
    assert "PUBLIC REPOSITORY GUIDE" in text
    assert not provider.commands


async def test_help_does_not_interrupt_a_running_realtime_tool(rt):
    import asyncio

    gate = asyncio.Event()

    class Resident:
        async def choose_activity(self, observation):
            await gate.wait()

    rt.sim.agents["Mei"] = Resident()
    rt.start_decision("Mei")
    try:
        with pytest.raises(Rejected, match="Finish your current operation"):
            rt.schedule("Mei", activities.use("help"))
    finally:
        await rt.close_running()


@pytest.mark.parametrize("fixture", ["engine", "rt"])
def test_setting_stays_stable_while_current_activity_and_clock_change(request, fixture):
    from runtime.activities.model import at, clock

    gate = request.getfixturevalue(fixture)
    setting = gate.observation("Mei").setting
    work = activities.work(gate)
    working = gate.observation("Mei")
    assert working.setting == setting
    assert work.id in working.situation and work.id not in setting
    assert clock(work.members["Mei"].end) in working.situation
    gate.leave("Mei", "Talk instead")
    conversation = activities.conversation(gate)
    gate.now = at(1, "08:05:07")
    talking = gate.observation("Mei")
    assert talking.setting == setting
    assert conversation.id in talking.situation
    assert "08:05:07" in talking.situation and "08:05:07" not in setting
    with pytest.raises(ValidationError):
        Card(talking.allowed).model.model_validate(
            {"thought": "Try work", "do": "submit your repair", "report": "Done"}
        )
    assert (
        "read" in gate.menu("Mei")["tools"]
        if fixture == "engine"
        else ("read" not in gate.menu("Mei")["tools"])
    )
