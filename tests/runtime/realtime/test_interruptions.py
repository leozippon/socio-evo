# ruff: noqa: F811
"""Reply bodies and activity selection react only to their explicit interruption events."""

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
    rt.speech_times["Mei"] = {"addressed_targets": ["Tomas"]}
    rt.speak("Mei", "First unconsumed speech", activity)
    rt.speech_times["Mei"] = {"addressed_targets": ["Tomas"]}
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


def open_local_chat(rt, who="Mei", topic="Fresh repair ideas"):
    rt.select(who, choose("start_chat", topic=topic))
    activity = rt.activities[rt.current[who]]
    rows = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
    opening = next(r for r in reversed(rows) if r["kind"] == "discussion")
    return activity, opening


@pytest.mark.parametrize("ended", [False, True])
async def test_planning_resumes_once_for_new_joinable_chat_with_latest_situation(rt, ended):
    from infrastructure.llm import Message

    for who in ("Mei", "Tomas", "Kofi"):
        rt.env.move(who, "workshop", time=rt.now // 60)
    resident = Resident(asyncio.Event())
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    await asyncio.sleep(0)
    old = rt.running["Tomas"]
    old.continuation.messages = (Message(role="assistant", content='{"thought":"Latest draft'),)
    activity, opening = open_local_chat(rt)
    assert old.invalidated
    # Neither later speech nor membership changes add cancellation causes for a planner.
    rt.enter(activity, "Kofi", rt.end)
    rt.enter(activity, "Ravi", rt.end)
    rt.speak("Mei", "A follow-up detail", activity)
    rt.leave("Kofi", "Continue elsewhere")
    if ended:
        rt.leave("Mei", "Finish this conversation")
    await rt.refresh_decisions()
    await asyncio.sleep(0)
    fresh = rt.running["Tomas"]
    assert fresh is not old and fresh.activity is None
    assert fresh.continuation is old.continuation
    assert fresh.continuation.messages[0].content == '{"thought":"Latest draft'
    assert fresh.decision_id == old.decision_id and fresh.request_id != old.request_id
    assert "Tomas" not in rt.current
    latest = resident.observations[-1]
    assert (activity.id in latest.allowed[0].menu["conversations"]) is not ended
    assert any("Fresh repair ideas" in p.text for p in latest.percepts)
    rows = cancellation_rows(rt)
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["mode"] == "resume"
    assert payload["changed_fields"] == ["open_conversations"]
    assert payload["event_ids"] == [opening["seq"]]
    assert payload["request_id"] == old.request_id
    if not ended:
        rt.enter(activity, "Aisha", rt.end)
        rt.speak("Mei", "More speech after selection resumed", activity)
        rt.leave("Aisha", "Leave again")
        await rt.refresh_decisions()
        assert rt.running["Tomas"] is fresh and not fresh.invalidated
        assert len(cancellation_rows(rt)) == 1
    await rt.close_running()


@pytest.mark.parametrize("access", ["public", "invited", "private", "remote", "outside"])
async def test_planning_new_arranged_chat_uses_existing_access_rules(rt, access):
    for who in ("Mei", "Kofi", "Tomas"):
        rt.env.move(who, "workshop", time=rt.now // 60)
    if access == "remote":
        rt.env.move("Tomas", "cafe", time=rt.now // 60)
    elif access == "outside":
        rt.outside["Tomas"] = "workshop"
    resident = Resident(asyncio.Event())
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    await asyncio.sleep(0)
    old = rt.running["Tomas"]
    people = ["Kofi", "Tomas"] if access == "invited" else ["Kofi"]
    rt.invitation_action(
        "Mei",
        "invite",
        {
            "people": people,
            "place": rt.env.world.places["workshop"].name,
            "at": None,
            "topic": "An arranged discussion",
            "public": access in ("public", "remote", "outside"),
        },
    )
    invitation = next(reversed(rt.invitations.values()))
    invitation.confirmed = ["Mei", "Kofi"]
    rt.start_ready_conversations()
    expected = access in ("public", "invited")
    assert old.invalidated is expected
    await rt.refresh_decisions()
    await asyncio.sleep(0)
    assert (rt.running["Tomas"] is not old) is expected
    if expected:
        latest = resident.observations[-1]
        assert invitation.conversation in latest.allowed[0].menu["conversations"]
        assert "An arranged discussion" in latest.situation
        rows = cancellation_rows(rt)
        assert len(rows) == 1 and rows[0]["payload"]["mode"] == "resume"
    else:
        assert not cancellation_rows(rt)
        assert not any(
            "An arranged discussion" in p.text for p in rt.env.log.pending_events("Tomas")
        )
    await rt.close_running()


@pytest.mark.parametrize("layer", ["creator", "work", "body", "rest"])
async def test_new_conversation_does_not_cancel_other_layers_or_auto_join(rt, layer):
    for who in ("Mei", "Tomas", "Kofi"):
        rt.env.move(who, "workshop", time=rt.now // 60)
    if layer == "work":
        work(rt, who="Tomas")
    elif layer == "body":
        conversation(rt)
    elif layer == "rest":
        rt.select("Tomas", choose("select_rest", arguments={"until": "10:00", "wake": False}))
    resident = Resident(asyncio.Event(), body=layer == "body")
    rt.sim.agents["Tomas"] = resident
    if layer != "rest":
        rt.start_decision("Tomas")
        if layer == "body":
            await finish(rt, "Tomas")
        await asyncio.sleep(0)
    old = rt.running.get("Tomas")
    activity, _ = open_local_chat(rt, who="Tomas" if layer == "creator" else "Kofi")
    await rt.refresh_decisions()
    assert rt.running.get("Tomas") is old
    assert not cancellation_rows(rt)
    assert ("Tomas" in activity.participants) is (layer == "creator")
    if layer == "rest":
        rt.wake_rests()
        assert isinstance(rt.activities[rt.current["Tomas"]], RestActivity)
    await rt.close_running()


async def test_new_chat_repairs_streamed_activity_selection_with_one_draft_and_latest_menu(
    rt, tmp_path
):
    from pathlib import Path

    from core.agent import Agent
    from experiments.config import ExperimentConfig
    from infrastructure.config import load_config
    from infrastructure.llm import LLMResponse

    started, resumed, finish_reply = (asyncio.Event() for _ in range(3))
    requests = []

    class Client:
        async def complete_stream(self, request, partial):
            requests.append(request)
            if len(requests) == 1:
                partial.text = '{"thought":"Consider the current choices'
                started.set()
                await asyncio.Event().wait()
            resumed.set()
            await finish_reply.wait()
            return LLMResponse(
                text=json.dumps(
                    {
                        "thought": "Rest here",
                        "do": "rest",
                        "day": "today",
                        "until": "10:00",
                        "wake for invitations": False,
                    }
                ),
                latency=1,
            )

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    listener = Agent.create(
        tmp_path / "Tomas", seed, Client(), config.cognition, config.environment.setting
    )
    rt.sim.agents["Tomas"] = listener
    for who in ("Mei", "Tomas"):
        rt.env.move(who, "workshop", time=rt.now // 60)
    rt.start_decision("Tomas")
    try:
        await asyncio.wait_for(started.wait(), 2)
        old = rt.running["Tomas"]
        activity, opening = open_local_chat(rt)
        await rt.refresh_decisions()
        await asyncio.wait_for(resumed.wait(), 2)
        assert len(requests) == 2
        repaired = requests[-1]
        assert sum(m.role == "assistant" for m in repaired.messages) == 1
        assert any("Consider the current choices" in m.content for m in repaired.messages)
        assert "Open conversations here:" in repaired.messages[-1].content
        assert activity.id in repaired.messages[-1].content
        assert repaired.metadata["decision_id"] == old.decision_id
        assert repaired.metadata["request_id"] != requests[0].metadata["request_id"]
        assert (
            repaired.metadata["context_usage"]["input_count"]
            <= repaired.metadata["context_usage"]["input_limit"]
        )
        assert cancellation_rows(rt)[0]["payload"]["event_ids"] == [opening["seq"]]
        finish_reply.set()
        await finish(rt, "Tomas")
        assert isinstance(rt.activities[rt.current["Tomas"]], RestActivity)
        assert "Tomas" not in activity.participants
    finally:
        await rt.close_running()
