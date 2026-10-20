# ruff: noqa: F811
"""Only an addressed conversation body reacts to relevant conversation changes."""

import asyncio
import json

import pytest

from core.interaction import Decision
from runtime.activities.model import RestActivity
from tests.runtime.activities.test_engine import choose, conversation, use, work
from tests.runtime.realtime.test_engine import engine, finish, rt  # noqa: F401


class Resident:
    def __init__(self, gate, *, body=False):
        self.gate = gate
        self.body = body
        self.observations = []
        self.commits = []

    async def choose_activity(self, observation, *, continuation=None):
        return await self.choose_tool(observation, continuation=continuation)

    async def choose_tool(self, observation, *, continuation=None):
        self.observations.append(observation)
        menu = observation.allowed[0].menu
        phase = menu.get("reply_phase")
        if continuation:
            continuation.begin()
        if phase == "intent" and self.body:
            decision = Decision(thought="", action=use("reply", targets=["Mei"]))
        else:
            await self.gate.wait()
            decision = Decision(
                thought="",
                action=use("reply", targets=menu["reply_targets"], text="Body accepted")
                if phase == "body"
                else choose("select_rest", arguments={"until": "10:00", "day": "today"}),
            )
        if continuation:
            continuation.stage(lambda: self.commits.append(phase))
        return decision


def cancellation_rows(rt, who="Tomas"):
    return [
        r
        for r in (json.loads(line) for line in rt.env.log.path.read_text().splitlines())
        if r["kind"] == "tool_cancelled" and r["actor"] == who
    ]


@pytest.mark.parametrize("layer", ["selection", "work", "body"])
async def test_arrivals_public_other_speech_and_other_claims_do_not_cancel(rt, layer):
    gate = asyncio.Event()
    if layer == "work":
        work(rt, who="Tomas")
    elif layer == "body":
        conversation(rt)
        rt.enter(rt.activities[rt.current["Tomas"]], "Aisha", rt.end)
    resident = Resident(gate, body=layer == "body")
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    if layer == "body":
        await finish(rt, "Tomas")
    await asyncio.sleep(0)
    job = rt.running["Tomas"]
    if layer == "body":
        rt.enter(rt.activities[rt.current["Tomas"]], "Ravi", rt.end)
    rt.env.move("Olga", "workshop", time=rt.now // 60)
    other = conversation(rt, people=("Olga", "Kofi"), public=True)
    rt.speak("Olga", "Public but unrelated", other)
    rt.emit("task_claimed", "Another job was taken", actor="Kofi", audience=["Tomas"])
    if layer == "body":
        rt.leave("Aisha", "A non-target leaves")
    await rt.refresh_decisions()
    assert rt.running["Tomas"] is job
    assert not job.task.cancelled() and not job.invalidated
    assert not cancellation_rows(rt)
    gate.set()
    if layer == "body":
        await finish(rt, "Tomas")
        if "Tomas" in rt.running:
            await finish(rt, "Tomas")
        assert resident.commits == ["body"]
    else:
        # Work's scripted result deliberately uses the supported direct-to-Rest path.
        await finish(rt, "Tomas")
    await rt.close_running()


@pytest.mark.parametrize("participants", [2, 3])
async def test_target_switch_to_rest_does_not_wait_forever_for_targeted_body(rt, participants):
    gate = asyncio.Event()
    activity = conversation(rt)
    if participants == 3:
        rt.enter(activity, "Aisha", rt.end)
    resident = Resident(gate, body=True)
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")
    await asyncio.sleep(0)
    old = rt.running["Tomas"]
    assert old.targets == ("Mei",)
    rt.schedule("Mei", choose("select_rest", arguments={"until": "10:00", "day": "today"}))
    await asyncio.wait_for(rt.refresh_decisions(), 2)
    rt.flush_leaves()
    assert isinstance(rt.activities[rt.current["Mei"]], RestActivity)
    assert rt.running.get("Tomas") is not old
    assert old.task.done()
    cancelled = cancellation_rows(rt)
    assert len(cancelled) == 1
    assert cancelled[0]["payload"]["event_ids"]
    assert cancelled[0]["payload"]["mode"] == ("stop" if participants == 2 else "resume")
    if participants == 2:
        assert not any(m.author == "Tomas" for m in activity.messages)
        assert not resident.commits
    await rt.close_running()


async def test_speech_before_body_first_turn_keeps_event_ids_and_percepts(rt):
    gate = asyncio.Event()
    activity = conversation(rt)
    resident = Resident(gate, body=True)
    perceived = []
    resident.perceive = lambda percepts: perceived.extend(p.text for p in percepts)
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")
    # The body task exists but has not had its first event-loop turn.
    rt.speak("Mei", "First unconsumed speech", activity)
    rt.speak("Mei", "Second unconsumed speech", activity)
    await rt.refresh_decisions()
    await asyncio.sleep(0)
    seen = perceived + [p.text for obs in resident.observations for p in obs.percepts]
    assert any("First unconsumed" in p for p in seen)
    assert any("Second unconsumed" in p for p in seen)
    rows = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
    speech_ids = [r["seq"] for r in rows if r["kind"] == "speech"]
    cancelled = cancellation_rows(rt)
    assert len(cancelled) == 1
    assert cancelled[0]["payload"]["event_ids"] == speech_ids
    assert cancelled[0]["payload"]["changed_fields"] == ["conversation_speech"]
    gate.set()
    await finish(rt, "Tomas")
    if "Tomas" in rt.running:
        await finish(rt, "Tomas")
    assert sum(m.text == "Body accepted" for m in activity.messages) == 1
    assert resident.commits == ["body"]
    await rt.close_running()


async def test_scheduler_stop_is_logged_once_and_does_not_resume_body(rt):
    gate = asyncio.Event()
    activity = conversation(rt)
    resident = Resident(gate, body=True)
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")
    await asyncio.sleep(0)
    job = rt.running["Tomas"]
    await rt.close_running()
    await rt.close_running()
    rows = cancellation_rows(rt)
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["mode"] == "stop"
    assert payload["changed_fields"] == ["scheduler_state"]
    assert payload["event_ids"] == []
    assert payload["request_id"] == job.request_id
    assert payload["decision_id"] == job.decision_id
    assert not rt.running and not resident.commits
    assert not activity.messages
