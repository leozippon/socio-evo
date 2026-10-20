# ruff: noqa: F811
"""Post-reply waiting uses the existing realtime tools without another decision."""

import asyncio
import json
from pathlib import Path

import pytest

from core.agent import Agent
from core.interaction import Decision
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import LLMResponse
from tests.runtime.activities.test_engine import choose, conversation, use
from tests.runtime.realtime.test_engine import engine, finish, rt  # noqa: F401
from tests.runtime.realtime.test_interruptions import Resident, open_local_chat


async def body_started(rt):
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")
    await asyncio.sleep(0)


def rows(rt):
    return [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]


async def test_real_two_phase_reply_starts_wait_after_completion_and_heard_speech_wakes(
    rt, tmp_path
):
    requests = []

    class Client:
        async def complete_stream(self, request, partial):
            requests.append(request)
            return LLMResponse(
                text=json.dumps(
                    {"thought": "Address Mei", "do": "reply", "targets": ["Mei"]}
                    if request.metadata["decision_phase"] == "intent"
                    else {"thought": "Answer Mei", "text": "Here is my answer"}
                ),
                latency=0,
            )

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    rt.sim.agents["Tomas"] = Agent.create(
        tmp_path / "Tomas", seed, Client(), config.cognition, config.environment.setting
    )
    activity = conversation(rt)
    try:
        await body_started(rt)
        await finish(rt, "Tomas")
        assert not activity.messages
        await finish(rt, "Tomas")
        wait = rt.running["Tomas"]
        assert wait.action == use("wait", seconds=300)
        await asyncio.sleep(0)
        assert not wait.task.done()  # Its own published speech did not cancel the wait.
        assert len(requests) == 2
        recorded = [r for r in rows(rt) if r["actor"] == "Tomas"]
        assert sum(r["kind"] == "decision" for r in recorded) == 1
        assert [(r["kind"], r["payload"].get("tool")) for r in recorded][-3:] == [
            ("speech", None),
            ("tool_completed", "reply"),
            ("tool_started", "wait"),
        ]
        other = conversation(rt, people=("Olga", "Kofi"))
        rt.speak("Olga", "Unheard in another conversation", other)
        await asyncio.sleep(0)
        assert not wait.task.done()
        rt.speak("Mei", "An audible response", activity)
        await finish(rt, "Tomas")
        assert wait.task.cancelled()
        assert "Tomas" not in rt.running
        assert len(requests) == 2
    finally:
        await rt.close_running()


@pytest.mark.parametrize("remaining", [1800, 43])
async def test_auto_wait_times_out_at_five_minutes_or_remaining_time(rt, monkeypatch, remaining):
    activity = conversation(rt)
    activity.members["Tomas"].end = rt.now + remaining
    delays = []
    sleep = asyncio.sleep

    async def advance(seconds):
        delays.append(seconds)
        rt.wall.value += seconds + 0.001
        await sleep(0)

    monkeypatch.setattr("runtime.realtime.engine.asyncio.sleep", advance)
    rt.schedule("Tomas", use("reply", targets=["Mei"], text="A direct reply"))
    start = rt.now
    await finish(rt, "Tomas")
    wait = rt.running["Tomas"]
    await finish(rt, "Tomas")
    assert delays == [min(300, remaining) / rt.settings.multiplier]
    assert rt.now - start == min(300, remaining)
    assert "Tomas" not in rt.running
    assert not wait.task.cancelled()
    assert rows(rt)[-1]["payload"]["tool"] == "wait"

    class Resident:
        async def choose_tool(self, observation):
            return Decision(
                thought="Rest after the pause",
                action=choose("select_rest", arguments={"until": "10:00", "day": "today"}),
            )

    rt.sim.agents["Tomas"] = Resident()
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")
    assert rt.activities[rt.current["Tomas"]].kind == "rest"


@pytest.mark.parametrize("arrival", ["body", "before_commit"])
@pytest.mark.parametrize("audible", [False, True])
async def test_new_speech_since_body_observation_skips_wait_only_when_audible(rt, arrival, audible):
    activity = conversation(rt)
    rt.enter(activity, "Aisha", rt.end)
    resident = Resident(asyncio.Event(), body=True)
    rt.sim.agents["Tomas"] = resident
    try:
        await body_started(rt)
        body = rt.running["Tomas"]
        if arrival == "before_commit":
            resident.gate.set()
            await finish(rt, "Tomas")
        if not audible:
            rt.env.world.locations["Tomas"] = "square"
        rt.speech_times["Mei"] = {"addressed_targets": ["Aisha"]}
        rt.speak("Mei", "New context for the group", activity)
        rt.env.world.locations["Tomas"] = activity.place
        assert not body.invalidated
        if arrival == "body":
            resident.gate.set()
            await finish(rt, "Tomas")
        # Delivery advanced every member cursor, so unread cannot detect this case.
        assert not activity.unread("Tomas")
        await finish(rt, "Tomas")
        assert activity.messages[-1].text == "Body accepted"
        assert ("Tomas" not in rt.running) is audible
        assert len(resident.observations) == 2
    finally:
        await rt.close_running()


async def test_resumed_body_resets_received_speech_before_wait(rt):
    activity = conversation(rt)
    resident = Resident(asyncio.Event(), body=True)
    rt.sim.agents["Tomas"] = resident
    try:
        await body_started(rt)
        first = rt.running["Tomas"]
        rt.speech_times["Mei"] = {"addressed_targets": ["Tomas"]}
        rt.speak("Mei", "The addressed update restarts this body", activity)
        await rt.refresh_decisions()
        await asyncio.sleep(0)
        resumed = rt.running["Tomas"]
        assert resumed.start == first.start  # Logical start cannot identify the observed messages.
        assert first.received_speech
        assert not resumed.received_speech
        resident.gate.set()
        await finish(rt, "Tomas")
        await finish(rt, "Tomas")
        assert rt.running["Tomas"].action.tool == "wait"
        assert len(resident.observations) == 3
    finally:
        await rt.close_running()


@pytest.mark.parametrize("closing", ["conversation", "day", "deferred", "remaining"])
async def test_started_reply_delivers_without_starting_wait_when_closing(rt, closing):
    activity = conversation(rt)
    rt.schedule("Tomas", use("reply", targets=["Mei"], text="The final reply"))
    if closing == "conversation":
        rt.closing.add(activity.id)
    elif closing == "day":
        rt.now = rt.end
        rt.clock.rebase(rt.now)
    elif closing == "deferred":
        rt.deferred["Tomas"] = "Leaving after this reply"
    else:
        activity.members["Tomas"].end = rt.now
    await finish(rt, "Tomas")
    assert activity.messages[-1].text == "The final reply"
    assert "Tomas" not in rt.running
    assert not any(r["payload"].get("tool") == "wait" for r in rows(rt))


@pytest.mark.parametrize("arrival", ["body", "before_commit", "after_wait"])
async def test_public_speech_from_another_conversation_prevents_or_wakes_auto_wait(rt, arrival):
    activity = conversation(rt)
    resident = Resident(asyncio.Event(), body=True)
    rt.sim.agents["Tomas"] = resident
    rt.env.move("Olga", activity.place, time=rt.now // 60)
    perceived = []
    resident.perceive = lambda percepts: perceived.extend(p.text for p in percepts)
    try:
        await body_started(rt)
        if arrival != "body":
            resident.gate.set()
            await finish(rt, "Tomas")
        if arrival == "after_wait":
            await finish(rt, "Tomas")
            assert rt.running["Tomas"].action.tool == "wait"
        other, _ = open_local_chat(rt, who="Olga")
        rt.speak("Olga", "News from the nearby public conversation", other)
        assert "Tomas" in other.messages[-1].audience
        assert not any(m.author == "Olga" for m in activity.messages)
        assert rt.running["Tomas"].received_speech
        if arrival == "body":
            resident.gate.set()
            await finish(rt, "Tomas")
        await finish(rt, "Tomas")
        assert "Tomas" not in rt.running
        assert activity.messages[-1].text == "Body accepted"
        assert len(resident.observations) == 2
        assert any("News from the nearby public conversation" in p for p in perceived)
    finally:
        await rt.close_running()
