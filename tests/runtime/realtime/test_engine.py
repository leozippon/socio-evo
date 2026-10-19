"""Controlled wall clocks and scripted agents; no model service, Docker or experiment."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from core.interaction import Card, Decision, EventKind
from runtime.activities.model import at
from runtime.realtime.clock import RealtimeTiming, WallClock
from runtime.realtime.engine import RealtimeEngine
from tests.runtime.activities import test_engine as activity_tests
from tests.runtime.activities.test_engine import (
    choose,
    conversation,
    use,
    work,
)

engine = activity_tests.engine


class ManualTime:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


@pytest.fixture
def rt(engine):
    wall = ManualTime()
    clock = WallClock(15, wall)
    clock.rebase(engine.now)
    result = RealtimeEngine(engine.sim, wall_clock=clock)
    result.now, result.end = engine.now, engine.end
    result.wall = wall
    return result


async def finish(rt, who):
    job = rt.running[who]
    await job.task
    if not job.task.cancelled():
        rt.now = job.task.result().end
    await rt.finish(who, job)


async def take(rt, who="Mei", job="task-1", partner=None):
    rt.schedule(who, use("claim", job=job, partner=partner))
    await finish(rt, who)
    return rt.env.board.claim_of(who)


def test_clock_scaling_rebase_and_no_backward_step():
    wall = ManualTime()
    clock = WallClock(24, wall)
    clock.rebase(at(1, "07:00"))
    wall.value += 10
    assert clock.now() == at(1, "07:04")
    wall.value -= 2
    assert clock.now() == at(1, "07:04")
    wall.value += 1000
    clock.rebase(at(2, "07:00"))
    assert clock.now() == at(2, "07:00")
    assert clock.delay(at(2, "07:04")) == 10


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_multiplier(value):
    with pytest.raises(ValidationError):
        RealtimeTiming(multiplier=value)


def test_new_cards_do_not_require_activity_duration_or_offer_read(rt):
    card = Card(rt.observation("Mei").allowed)
    reply = card.model.model_validate(
        {"thought": "Work now", "do": "work", "public": False, "mode": "parallel"}
    )
    rt.select("Mei", card.decision(reply).action)
    forms = json.dumps(Card(rt.observation("Mei").allowed).model.model_json_schema())
    assert "read new messages" not in forms
    assert "remaining usable time" not in rt.observation("Mei").situation
    assert "actual elapsed wall time" in rt.observation("Mei").setting


async def test_slow_model_does_not_hold_fast_resident_or_double_count_time(rt):
    slow, fast = asyncio.Event(), asyncio.Event()

    class Resident:
        def __init__(self, event):
            self.event = event

        async def choose_activity(self, obs):
            await self.event.wait()
            return Decision(
                thought="Rest", action=choose("select_rest", arguments={"until": "10:00"})
            )

    rt.sim.agents["Mei"] = Resident(slow)
    rt.sim.agents["Tomas"] = Resident(fast)
    rt.start_decision("Mei")
    rt.start_decision("Tomas")
    rt.wall.value += 1
    fast.set()
    await finish(rt, "Tomas")
    assert not rt.running["Mei"].task.done()
    assert "Tomas" in rt.current
    assert rt.now == at(1, "08:00:15")
    rt.wall.value += 4
    slow.set()
    await finish(rt, "Mei")
    assert rt.now == at(1, "08:01:15")  # shared 5 seconds, not 1+5 seconds


async def test_repository_result_only_visible_at_actual_completion(rt, monkeypatch):
    work(rt)
    await take(rt)
    done = asyncio.Event()
    provider = next(iter(rt.env.providers.values()))

    async def command(*args):
        await done.wait()
        return {"exit_code": 0, "output": "saved code"}

    monkeypatch.setattr(provider, "run_command", command)
    rt.schedule("Mei", use("command", command="test command"))
    assert not any(e.kind == EventKind.COMMAND_EXECUTED for e in rt.env.log.pending_events("Mei"))
    rt.wall.value += 5
    done.set()
    await finish(rt, "Mei")
    event = next(
        e for e in rt.env.log.pending_events("Mei") if e.kind == EventKind.COMMAND_EXECUTED
    )
    assert event.payload["sim_seconds"] == at(1, "08:01:15")
    assert "saved code" in event.text
    assert rt.now == at(1, "08:01:15")  # no fixed 300-second charge


async def test_speech_is_heard_directly_without_reading_or_length_charge(rt):
    activity = conversation(rt)
    gate = asyncio.Event()
    text = "Evidence " * 500

    class Speaker:
        async def choose_tool(self, obs):
            await gate.wait()
            return Decision(thought="Explain", action=use("reply", text=text))

    rt.sim.agents["Mei"] = Speaker()
    rt.start_decision("Mei")
    rt.wall.value += 5
    gate.set()
    await finish(rt, "Mei")
    await finish(rt, "Mei")
    heard = [p for p in rt.env.perceive("Tomas") if p.kind == EventKind.SPEECH]
    assert len(heard) == 1 and text in heard[0].text
    assert not activity.unread("Tomas")
    assert rt.now == at(1, "08:01:15")
    speech = next(e for e in rt.env.log.pending_events("Mei") if e.kind == EventKind.SPEECH)
    assert speech.payload["generation_wall_seconds"] == 5
    assert "read" not in rt.menu("Tomas")["tools"]


async def test_two_person_exit_waits_for_started_speech(rt):
    activity = conversation(rt)
    gate = asyncio.Event()

    class Listener:
        async def choose_tool(self, obs):
            await gate.wait()
            return Decision(thought="Answer", action=use("reply", text="The final answer"))

    rt.sim.agents["Tomas"] = Listener()
    rt.start_decision("Tomas")
    rt.leave("Mei", "Goodbye")
    assert set(activity.participants) == {"Mei", "Tomas"}
    assert activity.id in rt.closing
    rt.wall.value += 2
    gate.set()
    await finish(rt, "Tomas")
    rt.flush_leaves()
    assert activity.status == "ended" and not activity.participants
    assert any("The final answer" in p.text for p in rt.env.perceive("Mei"))


async def test_join_leave_and_onsite_delivery_permissions(rt):
    activity = conversation(rt, people=("Mei", "Tomas", "Aisha"), public=True)
    rt.speak("Mei", "First statement", activity)
    rt.leave("Aisha", "Go home")
    rt.speak("Mei", "Second statement", activity)
    rt.env.move("Kofi", "workshop", time=rt.now // 60)
    rt.select("Kofi", choose("select_conversation", target=activity.id))
    rt.speak("Tomas", "Third statement", activity)
    aisha = "\n".join(p.text for p in rt.env.perceive("Aisha"))
    kofi = "\n".join(p.text for p in rt.env.perceive("Kofi"))
    assert "First statement" in aisha and "Second statement" not in aisha
    assert "First statement" not in kofi and "Third statement" in kofi


async def test_closing_finishes_started_command_then_preserves_work(rt, monkeypatch):
    rt.wall.value += (at(1, "11:59") - rt.now) / 15
    rt.now = rt.clock.now()
    activity = work(rt)
    await take(rt)
    done = asyncio.Event()
    provider = next(iter(rt.env.providers.values()))

    async def command(*args):
        await done.wait()
        return {"exit_code": 0, "output": "finished after closing"}

    monkeypatch.setattr(provider, "run_command", command)
    rt.schedule("Mei", use("command", command="slow test"))
    rt.wall.value += 12
    rt.now = rt.clock.now()
    assert rt.now == at(1, "12:02")
    rt.boundary()
    assert "Mei" in rt.running and "Mei" in rt.current
    assert "command" not in rt.menu("Mei")["tools"]
    done.set()
    await finish(rt, "Mei")
    rt.flush_leaves()
    assert activity.status == "paused"
    assert rt.env.board.claim_of("Mei")
    assert rt.activities[rt.current["Mei"]].kind == "move"
    assert any("finished after closing" in p.text for p in rt.env.perceive("Mei"))


async def test_completed_relay_never_rebinds_to_new_job(rt):
    shared = work(rt, "Mei", public=True, mode="relay")
    work(rt, "Tomas")
    await take(rt, "Mei", "task-7", "Tomas")
    await take(rt, "Tomas", "task-7", "Mei")
    rt.menu("Mei")
    rt.leave("Tomas", "Join")
    rt.select("Tomas", choose("resume_work", target=shared.id))
    del rt.env.board.claims["task-7"]
    rt.retire_work()
    assert shared.status == "ended" and shared.task_id == "task-7"
    assert "Mei" not in rt.current and "Tomas" not in rt.current
    new = work(rt, "Tomas")
    await take(rt, "Tomas", "task-1")
    assert new.id != shared.id and "command" in rt.menu("Tomas")["tools"]


async def test_real_driver_rest_day_with_no_requests_after_closing(engine):
    class Resident:
        def __init__(self):
            self.calls = 0

        async def choose_activity(self, obs):
            self.calls += 1
            return Decision(
                thought="Rest",
                action=choose("select_rest", arguments={"until": "22:00", "wake": False}),
            )

    engine.sim.agents = {p: Resident() for p in engine.sim.agents}
    clock = WallClock(1_000_000)
    driver = RealtimeEngine(engine.sim, wall_clock=clock)
    await driver.run(at(1, "07:00") // 60)
    assert driver.now >= at(1, "22:00")
    assert not driver.running and not driver.current
    assert all(p.calls == 1 for p in engine.sim.agents.values())
    rows = [json.loads(x) for x in engine.env.log.path.read_text().splitlines()]
    assert [e["time"] for e in rows] == sorted(e["time"] for e in rows)


async def test_speech_wakes_wait_without_an_extra_read_action(rt):
    activity = conversation(rt)
    rt.schedule("Tomas", use("wait", seconds=300))
    await asyncio.sleep(0)
    rt.wall.value += 1
    rt.now = rt.clock.now()
    rt.speak("Mei", "A new finding", activity)
    await asyncio.sleep(0)
    job = rt.running["Tomas"]
    assert job.task.cancelled()
    await rt.finish("Tomas", job)
    assert "Tomas" not in rt.running
    assert any("A new finding" in p.text for p in rt.env.perceive("Tomas"))


async def test_leaving_does_not_wait_for_a_silent_wait_timer(rt):
    activity = conversation(rt)
    rt.schedule("Tomas", use("wait", seconds=300))
    await asyncio.sleep(0)
    rt.leave("Mei", "Finished talking")
    await asyncio.sleep(0)
    await rt.finish("Tomas", rt.running["Tomas"])
    rt.flush_leaves()
    assert activity.status == "ended"
    assert rt.now == at(1, "08:00")


async def test_invitation_cannot_take_resident_with_inflight_activity_selection(rt):
    gate = asyncio.Event()

    class Resident:
        async def choose_activity(self, obs):
            await gate.wait()
            return Decision(
                thought="Rest", action=choose("select_rest", arguments={"until": "09:00"})
            )

    rt.sim.agents["Mei"] = Resident()
    rt.start_decision("Mei")
    assert not rt.available("Mei")
    await rt.close_running()
    assert not rt.running


async def test_submission_freezes_snapshot_after_actual_tool_runtime(rt, monkeypatch):
    from core.environment import Trade

    activity = work(rt)
    await take(rt)
    provider = rt.env.providers[Trade.PROGRAMMING]
    gate = asyncio.Event()

    async def snapshot(*args):
        await gate.wait()
        return "frozen diff"

    monkeypatch.setattr(provider, "prepare_submission", snapshot)
    rt.schedule("Mei", use("submit", report="Ready"))
    rt.wall.value += 3
    gate.set()
    await finish(rt, "Mei")
    assert rt.assessments["task-1"]["action"]["solution"] == "frozen diff"
    assert rt.assessments["task-1"]["due"] == at(1, "08:00:45") + 1200
    assert "Mei" not in rt.current and activity.status == "paused"
    await rt.close()


async def test_immediate_controls_have_exactly_one_completion_event(rt):
    work(rt)
    await take(rt)
    rows = [json.loads(x) for x in rt.env.log.path.read_text().splitlines()]
    assert (
        len([r for r in rows if r["kind"] == "tool_completed" and r["payload"]["tool"] == "claim"])
        == 1
    )


async def test_speech_goes_into_actual_agent_memory_before_conversation_exit(rt, tmp_path):
    from pathlib import Path

    from core.agent import Agent
    from experiments.config import ExperimentConfig
    from infrastructure.config import load_config
    from infrastructure.llm import ScriptedClient

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    listener = Agent.create(
        tmp_path / "Tomas",
        seed,
        ScriptedClient(lambda r: None),
        config.cognition,
        config.environment.setting,
    )
    rt.sim.agents["Tomas"] = listener
    activity = conversation(rt)
    rt.speak("Mei", "The regression is caused by timezone parsing.", activity)
    rt.leave("Mei", "Finished")
    assert any("timezone parsing" in r.text for r in listener.memory.episodic.read())
    assert not rt.env.perceive("Tomas")  # already delivered, not requiring another decision


async def test_cancellation_closes_inflight_requests(rt):
    class Resident:
        async def choose_activity(self, obs):
            await asyncio.Event().wait()

    rt.sim.agents["Mei"] = Resident()
    rt.start_decision("Mei")
    job = rt.running["Mei"]
    await rt.close()
    assert job.task.cancelled() and not rt.running


async def test_venue_closing_does_not_wait_out_silent_conversation_timers(rt):
    activity = conversation(rt)
    rt.schedule("Tomas", use("wait", seconds=3600))
    await asyncio.sleep(0)
    rt.wall.value += (at(1, "12:00") - rt.now) / 15
    rt.now = rt.clock.now()
    rt.boundary()
    await asyncio.sleep(0)
    assert rt.running["Tomas"].task.cancelled()
    await rt.finish("Tomas", rt.running["Tomas"])
    rt.flush_leaves()
    assert activity.status == "ended"


async def test_day_end_records_completed_work_before_later_home_events(rt, monkeypatch):
    work(rt)
    await take(rt)
    gate = asyncio.Event()

    async def command(*args):
        await gate.wait()
        return {"exit_code": 0, "output": "last result"}

    monkeypatch.setattr(next(iter(rt.env.providers.values())), "run_command", command)
    # A started operation is drained while the day closes; new operations are rejected.
    rt.schedule("Mei", use("command", command="slow task"))
    rt.wall.value += (at(1, "22:01") - rt.now) / 15
    rt.now = rt.clock.now()
    rt.boundary()
    gate.set()
    await finish(rt, "Mei")
    rt.flush_leaves()
    assert rt.env.world.locations["Mei"] == rt.env.config.homes["Mei"]
    assert not rt.running
    rows = [json.loads(x) for x in rt.env.log.path.read_text().splitlines()]
    command_index = next(i for i, e in enumerate(rows) if e["kind"] == "command_executed")
    move_index = max(i for i, e in enumerate(rows) if e["kind"] == "move" and e["actor"] == "Mei")
    assert command_index < move_index
    assert rows[command_index]["time"] == 22 * 60 + 1


async def test_hearing_during_inference_keeps_persistent_memory_in_time_order(rt, tmp_path):
    from pathlib import Path

    from core.agent import Agent
    from experiments.config import ExperimentConfig
    from infrastructure.config import load_config
    from infrastructure.llm import LLMResponse

    gate = asyncio.Event()

    class Client:
        async def complete(self, request):
            await gate.wait()
            return LLMResponse(
                text=json.dumps({"thought": "Respond", "do": "reply", "text": "Thank you"}),
                latency=1,
            )

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    listener = Agent.create(
        tmp_path / "Tomas", seed, Client(), config.cognition, config.environment.setting
    )
    rt.sim.agents["Tomas"] = listener
    activity = conversation(rt)
    rt.start_decision("Tomas")
    await asyncio.sleep(0)
    rt.wall.value += 8
    rt.now = rt.clock.now()
    rt.speak("Mei", "A new discovery while you were thinking.", activity)
    gate.set()
    await finish(rt, "Tomas")
    await finish(rt, "Tomas")
    records = listener.memory.episodic.read()
    assert [r.time for r in records] == sorted(r.time for r in records)
    assert any("new discovery" in r.text for r in records)


def test_realtime_sleep_until_morning_does_not_repeat_failed_selections(rt):
    rt.now = at(1, "18:08")
    rt.select("Mei", choose("select_rest", arguments={"until": "06:00", "wake": False}))
    assert rt.activities[rt.current["Mei"]].members["Mei"].end == rt.end
    assert not rt.available("Mei")


async def test_repository_guide_is_pinned_and_readable_as_work_tool(rt, monkeypatch):
    provider = next(iter(rt.env.providers.values()))
    monkeypatch.setattr(
        provider, "work_guide", lambda part: "PUBLIC GUIDE: use tests/runtests.py", raising=False
    )
    work(rt)
    await take(rt)
    observation = rt.observation("Mei")
    assert "PUBLIC GUIDE" in observation.situation
    assert "guide" in rt.menu("Mei")["tools"]
    card = Card(observation.allowed)
    reply = card.model.model_validate(
        {"thought": "Check the launcher", "do": "read repository work guide"}
    )
    decision = card.decision(reply)
    assert decision.action.tool == "guide"
    rt.schedule("Mei", decision.action)
    await finish(rt, "Mei")
    activity = rt.activities[rt.current["Mei"]]
    assert "PUBLIC GUIDE" in activity.feedback["Mei"][-1]
    assert not provider.commands, "reading instructions must not run repository code"
    assert "guide" not in rt.menu("Jonas").get("tools", [])
