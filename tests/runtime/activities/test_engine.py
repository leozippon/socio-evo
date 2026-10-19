import asyncio
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.environment import Assessment, Environment, Trade
from core.environment.rejection import Rejected
from core.interaction import Card, Decision, time_at
from core.interaction.actions import Activity as Choice
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from runtime.activities.engine import ActivityEngine, ActivityLoopError
from runtime.activities.model import (
    ConversationActivity,
    EventQueue,
    Timing,
    at,
    clock,
    units,
)
from runtime.scheduler import TriggerQueue
from tests.core.environment.test_technical_community import RepositoryProvider


class PrivateRepositories(RepositoryProvider):
    def __init__(self):
        self.commands = []
        self.patches = {}
        self.assessed = []
        self.conflict = False
        self.verdict_ready = None

    async def run_command(self, part, worker, task_id, command):
        self.commands.append((worker, command))
        self.patches[(worker, task_id)] = self.patches.get((worker, task_id), "") + "\nedit"
        return {"exit_code": 0, "output": "repository evidence"}

    async def prepare_submission(self, part, worker, task_id, solution):
        return self.patches.get((worker, task_id), "")

    async def export_handoff(self, part, worker, task_id):
        return self.patches.get((worker, task_id), "")

    async def apply_handoff(self, part, worker, task_id, patch):
        if self.conflict:
            return {"exit_code": 1, "output": "conflicting edits"}
        self.patches[(worker, task_id)] = patch
        return {"exit_code": 0, "output": "applied"}

    async def assess(self, part, patch):
        self.assessed.append(patch)
        if self.verdict_ready is not None:
            await self.verdict_ready.wait()
        return Assessment(passed=True, quality=1, feedback="Accepted")


@pytest.fixture
def engine(tmp_path):
    config = load_config(Path("experiments/configs/community/activities.yaml"), ExperimentConfig)
    provider = PrivateRepositories()
    env = Environment.create(
        config.environment, list(config.environment.homes), provider, tmp_path / "events.jsonl"
    )
    env.post(time_at(1, "07:00"), 0)
    sim = SimpleNamespace(
        env=env,
        config=config.simulation,
        seed=0,
        rng=random.Random(3),
        agents={a: None for a in env.agents},
        queue=TriggerQueue(),
        _met={a: set() for a in env.agents},
        _bound_lapses=lambda: None,
        activity_state={},
    )
    result = ActivityEngine(sim)
    result.now = at(1, "08:00")
    result.end = at(1, "22:00")
    return result


def events(engine):
    return [json.loads(x) for x in engine.env.log.path.read_text().splitlines()]


def choose(operation, **kwargs):
    return Choice(operation=operation, **kwargs)


def use(name, **args):
    return Choice(operation="activity_tool", tool=name, arguments=args)


def work(engine, who="Mei", seconds=3600, public=False, mode="parallel"):
    engine.env.move(who, "workshop", time=engine.now // 60)
    engine.select(
        who, choose("select_work", seconds=seconds, arguments={"public": public, "mode": mode})
    )
    return engine.activities[engine.current[who]]


async def complete(engine, when):
    engine.now = when
    for e in engine.queue.pop_at(when):
        await engine.process(e)


async def claim(engine, who="Mei", job="task-1", partner=None):
    engine.schedule(who, use("claim", job=job, partner=partner))
    await complete(engine, engine.now)
    return engine.env.board.claim_of(who)


def conversation(engine, people=("Mei", "Tomas"), public=False):
    activity = ConversationActivity(
        id=engine.identifier("conversation"),
        place="workshop",
        start=engine.now,
        latest_end=engine.now + 1800,
        topic="A repair",
        public=public,
        invited=people,
    )
    for who in people:
        engine.env.move(who, "workshop", time=engine.now // 60)
        engine.enter(activity, who, activity.latest_end)
    return activity


def test_seconds_clock_queue_and_text_costs():
    assert at(2, "08:00:30") == 115230
    assert clock(at(2, "08:00:30")) == "08:00:30"
    assert units("你好 world, three words!") == 5
    assert Timing().text_cost("hello") == 1
    assert Timing().text_cost("a " * 500) == 120
    queue = EventQueue()
    queue.add(5, "end", priority=2)
    queue.add(5, "tool", priority=0)
    assert [e.kind for e in queue.pop_at(5)] == ["tool", "end"]


def test_two_level_card_and_no_morning_goal(engine):
    first = engine.observation("Mei")
    assert first.decision_layer == "choose_activity"
    assert "set today's goal" not in str(Card(first.allowed).model.model_json_schema())
    work(engine)
    tool = engine.observation("Mei")
    assert tool.decision_layer == "activity_tool"
    assert "remaining usable time" in tool.situation
    assert "Tool costs" in tool.situation
    assert "select_work" not in str(Card(tool.allowed).model.model_json_schema())


async def test_claim_is_zero_time_and_tool_effects_wait_until_completion(engine):
    activity = work(engine)
    start = engine.now
    await claim(engine)
    assert engine.now == start and activity.task_id == "task-1"
    engine.schedule("Mei", use("command", command="pytest"))
    assert not engine.env.providers[Trade.PROGRAMMING].commands
    assert engine.pending["Mei"].end == start + 300
    await complete(engine, start + 300)
    assert engine.env.providers[Trade.PROGRAMMING].commands == [("Mei", "pytest")]
    assert engine.current["Mei"] == activity.id
    assert engine.remaining("Mei") == 3300


async def test_tools_cannot_cross_budget_or_work_closing(engine):
    engine.now = at(1, "11:56")
    work(engine)
    await claim(engine)
    with pytest.raises(Rejected, match="unavailable"):
        engine.schedule("Mei", use("test", command="pytest"))
    observation = engine.observation("Mei")
    assert "240 seconds" in observation.situation and "Time reminder" in observation.situation
    engine.schedule("Mei", use("read_code", path="x.py", line=1, lines=100))
    await complete(engine, at(1, "11:57"))
    assert engine.remaining("Mei") == 180


async def test_pause_resume_keeps_activity_and_private_progress(engine):
    activity = work(engine)
    await claim(engine)
    engine.schedule("Mei", use("command", command="edit"))
    await complete(engine, engine.now + 300)
    before = engine.env.providers[Trade.PROGRAMMING].patches.copy()
    engine.schedule("Mei", use("leave"))
    await complete(engine, engine.now)
    assert activity.status == "paused" and "Mei" not in engine.current
    engine.select("Mei", choose("resume_work", target=activity.id, seconds=1800))
    assert engine.current["Mei"] == activity.id
    assert engine.env.providers[Trade.PROGRAMMING].patches == before
    assert engine.remaining("Mei") == 1800
    assert "preserved" in activity.result["Mei"]


async def test_public_work_private_workspaces_and_explicit_handoff(engine):
    activity = work(engine, public=True)
    work(engine, "Tomas")
    joint = "task-7"
    await claim(engine, "Mei", joint, "Tomas")
    await claim(engine, "Tomas", joint, "Mei")
    # Join one public work activity; operations remain independent.
    engine.leave("Tomas", "join partner")
    activity.task_id = joint
    engine.select("Tomas", choose("resume_work", target=activity.id, seconds=1800))
    engine.schedule("Mei", use("command", command="edit Mei"))
    await complete(engine, engine.now + 300)
    provider = engine.env.providers[Trade.PROGRAMMING]
    assert ("Tomas", joint) not in provider.patches
    engine.schedule("Mei", use("handoff", to="Tomas", description="Fix and test evidence"))
    await complete(engine, engine.now + 60)
    handoff = next(iter(engine.handoffs.values()))
    frozen = handoff.patch
    provider.patches[("Mei", joint)] = "later changes"
    engine.schedule("Tomas", use("apply_handoff", handoff=handoff.id))
    await complete(engine, engine.now + 60)
    assert provider.patches[("Tomas", joint)] == frozen
    assert handoff.status == "accepted"


async def test_handoff_conflict_preserves_recipient_and_relay_ownership(engine):
    activity = work(engine, public=True, mode="relay")
    work(engine, "Tomas")
    await claim(engine, "Mei", "task-7", "Tomas")
    await claim(engine, "Tomas", "task-7", "Mei")
    activity.task_id = "task-7"
    engine.leave("Tomas", "join")
    engine.select("Tomas", choose("resume_work", target=activity.id, seconds=1800))
    assert "edit" not in engine.menu("Tomas")["tools"]
    provider = engine.env.providers[Trade.PROGRAMMING]
    provider.patches[("Mei", "task-7")] = "incoming"
    provider.patches[("Tomas", "task-7")] = "old"
    engine.schedule("Mei", use("handoff", to="Tomas", description="Your turn"))
    await complete(engine, engine.now + 60)
    handoff = next(iter(engine.handoffs.values()))
    assert activity.relay_owner is None
    provider.conflict = True
    engine.schedule("Tomas", use("apply_handoff", handoff=handoff.id))
    await complete(engine, engine.now + 60)
    assert provider.patches[("Tomas", "task-7")] == "old" and handoff.status == "offered"
    provider.conflict = False
    engine.schedule("Tomas", use("apply_handoff", handoff=handoff.id))
    await complete(engine, engine.now + 60)
    assert activity.relay_owner == "Tomas" and "edit" in engine.menu("Tomas")["tools"]


async def test_message_visibility_read_cursor_and_no_fixed_turns(engine):
    activity = conversation(engine)
    start = engine.now
    engine.schedule("Mei", use("reply", text="Hello partner"))
    engine.schedule("Tomas", use("reply", text="Hello Mei"))
    assert not activity.messages
    await complete(engine, start + 1)
    assert len(activity.messages) == 2
    observation = engine.observation("Tomas")
    assert not any("Hello partner" in p.text for p in observation.percepts)
    assert "Hello partner" not in observation.situation
    engine.schedule("Tomas", use("read"))
    await complete(engine, engine.now + 1)
    observation = engine.observation("Tomas")
    assert any("Hello partner" in p.text for p in observation.percepts)
    assert not activity.unread("Tomas")


async def test_join_only_future_messages_and_departure_keeps_group(engine):
    activity = conversation(engine, ("Mei", "Tomas", "Aisha"), public=True)
    engine.schedule("Mei", use("reply", text="Before joining"))
    await complete(engine, engine.now + 1)
    engine.env.move("Kofi", "workshop", time=engine.now // 60)
    engine.select("Kofi", choose("select_conversation", target=activity.id, seconds=600))
    assert not activity.unread("Kofi")
    engine.leave("Aisha", "Finished")
    assert activity.status == "active" and len(activity.participants) == 3
    engine.schedule("Mei", use("reply", text="After joining"))
    await complete(engine, engine.now + 1)
    assert [m.text for m in activity.unread("Kofi")] == ["After joining"]
    assert not activity.unread("Aisha")
    engine.leave("Kofi", "Finished")
    engine.leave("Mei", "Finished")
    assert activity.status == "ended" and not activity.participants


async def test_wait_for_message_wakes_once_and_reply_cost_tracks_length(engine):
    activity = conversation(engine)
    engine.schedule("Tomas", use("wait", seconds=600))
    engine.schedule("Mei", use("reply", text="one " * 250))
    assert engine.pending["Mei"].end == engine.now + 60
    await complete(engine, engine.now + 60)
    assert "Tomas" not in engine.pending and activity.unread("Tomas")
    assert "Mei" not in engine.pending


async def test_invitation_does_not_interrupt_busy_command(engine):
    work(engine, "Mei")
    await claim(engine)
    engine.schedule("Mei", use("command", command="test"))
    busy = engine.pending["Mei"]
    engine.env.move("Tomas", "workshop", time=engine.now // 60)
    engine.invitation_action(
        "Tomas",
        "invite",
        {
            "people": ["Mei"],
            "place": "the Workshop",
            "at": None,
            "minutes": 20,
            "topic": "Repair",
            "public": False,
        },
    )
    engine.wake_rests()
    engine.start_ready_conversations()
    assert engine.pending["Mei"] is busy
    await complete(engine, busy.end)
    assert engine.current["Mei"] in engine.activities
    assert engine.invitation_ids("Mei")


async def test_appointment_requires_confirmed_present_free_and_has_grace(engine):
    engine.env.move("Mei", "workshop", time=engine.now // 60)
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas", "Aisha"],
            "place": "the Workshop",
            "at": "08:10",
            "minutes": 20,
            "topic": "Repair",
            "public": False,
        },
    )
    invitation = next(iter(engine.invitations.values()))
    engine.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    await complete(engine, at(1, "08:10"))
    engine.start_ready_conversations()
    assert invitation.status == "pending"
    engine.now = at(1, "08:15")
    engine.env.move("Tomas", "workshop", time=engine.now // 60)
    await complete(engine, engine.now)
    assert invitation.status == "started"
    conv = engine.activities[invitation.conversation]
    assert set(conv.participants) == {"Mei", "Tomas"}
    assert "Aisha" not in engine.current


async def test_appointment_without_two_arrivals_is_cancelled(engine):
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas"],
            "place": "the Workshop",
            "at": "08:10",
            "minutes": 20,
            "topic": "Repair",
            "public": False,
        },
    )
    invitation = next(iter(engine.invitations.values()))
    await complete(engine, at(1, "08:10"))
    await complete(engine, at(1, "08:15"))
    assert invitation.status == "cancelled"


async def test_background_assessment_delay_and_payout(engine):
    work(engine)
    await claim(engine)
    provider = engine.env.providers[Trade.PROGRAMMING]
    provider.patches[("Mei", "task-1")] = "frozen repair"
    provider.verdict_ready = asyncio.Event()
    await engine.submit("Mei", "Fixed and locally tested")
    assert "Mei" not in engine.current
    start = engine.now
    await asyncio.sleep(0)
    provider.patches[("Mei", "task-1")] = "later changes"
    await complete(engine, start + 1200)
    assert engine.assessments["task-1"]["delayed"]
    assert not any(e["kind"] == "work_submitted" for e in events(engine))
    provider.verdict_ready.set()
    await asyncio.sleep(0)
    await complete(engine, start + 1500)
    assert not engine.assessments and provider.assessed == ["frozen repair"]
    assert any(e["kind"] == "payment" for e in events(engine))


async def test_state_roundtrip_keeps_paused_work_handoffs_and_pending_assessment(engine):
    activity = work(engine)
    await claim(engine)
    provider = engine.env.providers[Trade.PROGRAMMING]
    provider.verdict_ready = asyncio.Event()
    await engine.submit("Mei", "Repair")
    saved = json.loads(json.dumps(engine.state()))
    restored = ActivityEngine(engine.sim, saved)
    assert restored.activities[activity.id].status == "paused"
    assert restored.assessments["task-1"]["action"]["report"] == "Repair"
    restored.protect_assessment_deadlines(4)
    assert engine.env.board.claims["task-1"].due_day >= 4
    await engine.close()


class ScriptedResident:
    def __init__(self, choose_fn, tool_fn=None):
        self.choose_fn = choose_fn
        self.tool_fn = tool_fn
        self.selections = []
        self.tools = []

    async def choose_activity(self, observation):
        self.selections.append(observation)
        return Decision(thought="Choose next activity", action=self.choose_fn(observation))

    async def choose_tool(self, observation):
        self.tools.append(observation)
        return Decision(thought="Continue this activity", action=self.tool_fn(observation))


async def test_full_event_driver_uses_two_layers_without_per_tool_activity_replanning(engine):
    selection_count = 0
    tool_count = 0

    def select_mei(observation):
        nonlocal selection_count
        selection_count += 1
        if selection_count == 1:
            return choose("select_rest", arguments={"until": "07:56", "wake": True})
        if selection_count == 2:
            return choose("select_move", target="workshop")
        if selection_count == 3:
            return choose("select_work", seconds=3600)
        return choose("select_rest", arguments={"until": "22:00", "wake": True})

    def tool_mei(observation):
        nonlocal tool_count
        tool_count += 1
        if tool_count == 1:
            return use("claim", job="task-1", partner=None)
        if tool_count in (2, 3):
            return use("command", command="inspect" if tool_count == 2 else "test")
        return use("leave")

    for who in engine.sim.agents:
        engine.sim.agents[who] = ScriptedResident(
            lambda o: choose("select_rest", arguments={"until": "22:00", "wake": True})
        )
    resident = ScriptedResident(select_mei, tool_mei)
    engine.sim.agents["Mei"] = resident
    await engine.run(time_at(1, "07:00"))
    # Initial rest/move/work, then uninterrupted rest inside the workplace until day end.
    assert selection_count == 4
    assert [o.time for o in resident.tools] == [480, 480, 485, 490]
    assert engine.env.providers[Trade.PROGRAMMING].commands == [("Mei", "inspect"), ("Mei", "test")]
    assert not engine.current and not engine.pending
    assert engine.sim.activity_state["activities"]
    assert all(
        engine.env.world.locations[a] == engine.env.config.homes[a] for a in engine.sim.agents
    )
    exact = [e["payload"]["sim_seconds"] for e in events(engine) if "sim_seconds" in e["payload"]]
    assert exact == sorted(exact)


async def test_zero_time_transition_loop_is_reported_without_advancing_time(engine):
    for who in engine.sim.agents:
        engine.sim.agents[who] = ScriptedResident(
            lambda o: choose("select_rest", arguments={"until": "22:00", "wake": True})
        )
    engine.sim.agents["Mei"] = ScriptedResident(
        lambda o: choose("select_work", seconds=60), lambda o: use("leave")
    )
    with pytest.raises(ActivityLoopError):
        await engine.run(time_at(1, "07:00"))
    assert engine.now == at(1, "07:00")


@pytest.mark.parametrize("wake", [True, False])
def test_rest_can_allow_or_ignore_invitation_wake(engine, wake):
    engine.select("Mei", choose("select_rest", arguments={"until": "10:00", "wake": wake}))
    engine.invitation_action(
        "Tomas",
        "invite",
        {
            "people": ["Mei"],
            "place": "the Workshop",
            "at": None,
            "minutes": 20,
            "topic": "A repair",
            "public": False,
        },
    )
    engine.wake_rests()
    assert ("Mei" not in engine.current) == wake


async def test_stale_wait_event_cannot_complete_a_new_operation(engine):
    activity = conversation(engine)
    start = engine.now
    engine.schedule("Tomas", use("wait", seconds=10))
    engine.schedule("Mei", use("reply", text="Hello"))
    await complete(engine, start + 1)
    engine.schedule("Tomas", use("reply", text="a " * 200))
    pending = engine.pending["Tomas"]
    await complete(engine, start + 10)
    assert engine.pending["Tomas"] is pending
    await complete(engine, pending.end)
    assert len(activity.messages) == 2


async def test_tool_finishes_at_closing_then_resident_chooses_next_activity(engine):
    engine.now = at(1, "11:55")
    work(engine)
    await claim(engine)
    engine.schedule("Mei", use("test", command="tests"))
    await complete(engine, at(1, "12:00"))
    engine.boundary()
    assert len(engine.env.providers[Trade.PROGRAMMING].commands) == 1
    assert "Mei" not in engine.current
    assert engine.env.world.locations["Mei"] == "workshop"
    assert "Mei" not in engine.outside


async def test_move_can_cross_origin_closing_and_cannot_use_work_tools(engine):
    engine.now = at(1, "11:59")
    engine.env.move("Mei", "workshop", time=engine.now // 60)
    home = engine.env.config.homes["Mei"]
    engine.select("Mei", choose("select_move", target=home))
    moving = engine.activities[engine.current["Mei"]]
    engine.now = at(1, "12:00")
    engine.boundary()
    assert engine.current["Mei"] == moving.id
    with pytest.raises(Rejected):
        engine.schedule("Mei", use("command", command="no"))
    await complete(engine, moving.latest_end)
    assert engine.env.world.locations["Mei"] == home


async def test_actual_agent_entrypoints_share_memory_but_separate_request_purposes(
    engine, tmp_path
):
    from core.agent import Agent
    from infrastructure.llm import ScriptedClient

    cfg = load_config(Path("experiments/configs/community/activities.yaml"), ExperimentConfig)
    seen = []

    def reply(request):
        seen.append(request)
        if request.metadata["purpose"] == "choose_activity":
            return {
                "thought": "Find work",
                "do": "work",
                "minutes": 60,
                "public": False,
                "mode": "parallel",
            }
        return {
            "thought": "Choose this issue",
            "do": "take a job",
            "job": "task-1",
            "partner": None,
        }

    agent = Agent.create(
        tmp_path / "Mei",
        cfg.agents[0],
        ScriptedClient(reply),
        cfg.cognition,
        cfg.environment.setting,
    )
    first = await agent.choose_activity(engine.observation("Mei"))
    engine.select("Mei", first.action)
    second = await agent.choose_tool(engine.observation("Mei"))
    assert second.action.tool == "claim"
    assert [r.metadata["purpose"] for r in seen] == ["choose_activity", "activity_tool"]
    assert "remaining usable time" in seen[-1].messages[-1].content
    assert agent.memory.episodic.read()


async def test_relay_permissions_cover_preexisting_private_work(engine):
    private = work(engine, "Tomas")
    shared = work(engine, "Mei", public=True, mode="relay")
    await claim(engine, "Mei", "task-7", "Tomas")
    await claim(engine, "Tomas", "task-7", "Mei")
    engine.menu("Mei")  # bind the newly claimed job to its public session
    assert "edit" in engine.menu("Mei")["tools"]
    assert "edit" not in engine.menu("Tomas")["tools"]
    assert private.id != shared.id
    engine.schedule("Mei", use("handoff", to="Tomas", description="Continue the repair"))
    await complete(engine, engine.now + engine.timing.handoff_seconds)
    handoff = next(iter(engine.handoffs))
    engine.schedule("Tomas", use("apply_handoff", handoff=handoff))
    await complete(engine, engine.now + engine.timing.handoff_seconds)
    assert shared.relay_owner == "Tomas"
    assert "edit" in engine.menu("Tomas")["tools"]
    assert "edit" not in engine.menu("Mei")["tools"]


async def test_close_cancels_background_coroutine_but_keeps_frozen_submission(engine):
    work(engine)
    await claim(engine)
    provider = engine.env.providers[Trade.PROGRAMMING]
    provider.verdict_ready = asyncio.Event()
    await engine.submit("Mei", "Ready for acceptance")
    await asyncio.sleep(0)
    future = next(iter(engine.futures.values()))
    await engine.close()
    assert future.cancelled()
    assert engine.state()["assessments"]["task-1"]["action"]["solution"] == ""


async def test_private_group_invites_newcomer_without_interrupting_existing_members(engine):
    activity = conversation(engine)
    engine.schedule("Mei", use("reply", text="Earlier private detail"))
    await complete(engine, engine.now + 1)
    engine.schedule("Mei", use("invite_here", people=["Aisha"]))
    await complete(engine, engine.now + engine.timing.invite_seconds)
    invitation = next(iter(engine.invitations.values()))
    assert not engine.conversation_access("Aisha", activity)
    engine.env.move("Aisha", "workshop", time=engine.now // 60)
    engine.invitation_action("Aisha", "accept", {"invitation": invitation.id})
    engine.start_ready_conversations()
    assert engine.current["Aisha"] == activity.id
    assert set(activity.participants) == {"Mei", "Tomas", "Aisha"}
    assert not activity.unread("Aisha")
    assert invitation.status == "started"


async def test_pending_acceptance_prompt_allows_rest_socializing_and_explains_job_slot(engine):
    work(engine)
    await claim(engine)
    await engine.submit("Mei", "Ready for acceptance")
    prompt = engine.observation("Mei")
    assert "awaiting background acceptance" in prompt.situation
    assert "socialize or rest" in prompt.situation
    assert "one-job slot" in prompt.situation
    assert "without priority" in prompt.situation
    assert "Do not resubmit" in engine.activity_help("Mei")
    assert "claim" not in engine.menu("Mei").get("tools", [])
    engine.now += engine.timing.assessment_seconds
    await asyncio.sleep(0)
    await engine.assessment("task-1")
    assert engine.env.board.claim_of("Mei") is None
    assert "awaiting background acceptance" not in engine.current_facts("Mei")
    await engine.close()


async def test_infrastructure_failure_retries_same_snapshot_and_pays_only_once(engine, monkeypatch):
    from core.environment import Assessment
    from core.environment.rejection import AssessmentUnavailable, Rejected

    work(engine)
    await claim(engine)
    provider = next(iter(engine.env.providers.values()))
    provider.patches[("Mei", "task-1")] = "original frozen repair"
    seen = []

    async def assess(part, patch):
        seen.append(patch)
        if len(seen) == 1:
            raise AssessmentUnavailable("GitHub timed out")
        return Assessment(passed=True, quality=1, feedback="Accepted")

    monkeypatch.setattr(provider, "assess", assess)
    await engine.submit("Mei", "Original report")
    await asyncio.sleep(0)
    engine.now += engine.timing.assessment_seconds
    await engine.assessment("task-1")
    entry = engine.assessments["task-1"]
    assert entry["retry_at"] == engine.now + engine.timing.assessment_retry_seconds
    assert entry["retry_attempts"] == 1
    assert engine.env.board.claim_of("Mei") is not None
    assert not any(e["kind"] == "payment" for e in events(engine))
    notice = [e for e in events(engine) if e["kind"] == "work_delayed"][-1]
    assert notice["payload"]["automatic_retry"] is True
    assert "Do not resubmit" in notice["text"]
    assert "automatically retry" in engine.current_facts("Mei")
    provider.patches[("Mei", "task-1")] = "later different work"
    with pytest.raises(Rejected):
        await engine.submit("Mei", "Do not replace pending snapshot")
    engine.now = entry["retry_at"] - 1
    await engine.assessment("task-1")
    assert len(seen) == 1 and "task-1" not in engine.futures
    engine.now += 1
    await engine.assessment("task-1")
    await asyncio.sleep(0)
    await engine.assessment("task-1")
    assert seen == ["original frozen repair", "original frozen repair"]
    assert not engine.assessments and engine.env.board.claim_of("Mei") is None
    assert len([e for e in events(engine) if e["kind"] == "payment"]) == 1
    await engine.assessment("task-1")
    assert len(seen) == 2
    await engine.close()


async def test_real_failed_verdict_is_returned_for_rework_without_automatic_retry(
    engine, monkeypatch
):
    from core.environment import Assessment

    work(engine)
    await claim(engine)
    provider = next(iter(engine.env.providers.values()))

    async def failed(*args):
        return Assessment(passed=False, quality=0, feedback="Regression failed")

    monkeypatch.setattr(provider, "assess", failed)
    await engine.submit("Mei", "Repair")
    await asyncio.sleep(0)
    engine.now += engine.timing.assessment_seconds
    await engine.assessment("task-1")
    assert not engine.assessments
    assert engine.env.board.claim_of("Mei") is not None
    assert not any(e["kind"] == "work_delayed" for e in events(engine))
    await engine.close()


async def test_pending_retry_restores_backoff_without_early_request(engine, monkeypatch):
    from core.environment.rejection import AssessmentUnavailable

    work(engine)
    await claim(engine)
    provider = next(iter(engine.env.providers.values()))
    seen = []

    async def outage(*args):
        seen.append(args)
        raise AssessmentUnavailable("offline")

    monkeypatch.setattr(provider, "assess", outage)
    await engine.submit("Mei", "Repair")
    await asyncio.sleep(0)
    engine.now += engine.timing.assessment_seconds
    await engine.assessment("task-1")
    saved = json.loads(json.dumps(engine.state()))
    restored = ActivityEngine(engine.sim, saved)
    retry = saved["assessments"]["task-1"]["retry_at"]
    restored.now, restored.end = retry - 1, engine.end
    restored.start_assessment("task-1")
    assert not restored.futures and len(seen) == 1
    restored.now = retry
    restored.start_assessment("task-1")
    await asyncio.sleep(0)
    await restored.assessment("task-1")
    assert len(seen) == 2
    assert restored.assessments["task-1"]["retry_attempts"] == 2
    assert restored.assessments["task-1"]["retry_at"] == retry + 600
    assert restored.env.board.claim_of("Mei").grace_days == 1
    await restored.close()
    await engine.close()
