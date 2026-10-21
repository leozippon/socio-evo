"""Work note generation shares decision cancellation, never the town's event loop."""

import asyncio

import pytest

from core.agent import Agent, CognitionConfig
from core.agent.config import WorkNotesConfig
from core.interaction import EventKind, Percept
from infrastructure.llm import ScriptedClient
from runtime.activities.model import at
from tests.core.agent.conftest import SEED, TOWN
from tests.runtime.activities.test_engine import engine, use, work  # noqa: F401
from tests.runtime.realtime.test_engine import finish, rt, take  # noqa: F401


@pytest.mark.parametrize("boundary", ["lunch", "closing"])
async def test_summary_yields_to_other_work_and_mandatory_departure(
    rt,  # noqa: F811
    tmp_path,
    boundary,
):
    started, release = asyncio.Event(), asyncio.Event()

    class Client:
        async def complete(self, request):
            if request.metadata["purpose"] == "work_summary":
                started.set()
                await release.wait()
                return await ScriptedClient(lambda _: {"summary": "Stored."}).complete(request)
            return await ScriptedClient(
                lambda _: {
                    "thought": "Put the repair aside",
                    "do": "leave this activity",
                }
            ).complete(request)

    resident = Agent.create(
        tmp_path / "resident",
        SEED,
        Client(),
        CognitionConfig(work_notes=WorkNotesConfig(enabled=True)),
        TOWN,
    )
    rt.sim.agents["Mei"] = resident
    work(rt)
    await take(rt)
    resident.memory.work.begin_activity(rt.current["Mei"], "task-1", rt.now // 60)
    resident.perceive(
        [
            Percept(
                seq=10000,
                time=rt.now // 60,
                kind=EventKind.COMMAND_EXECUTED,
                task_id="task-1",
                activity_id=rt.current["Mei"],
                text="SAVED_RESULT",
            )
        ]
    )
    rt.start_decision("Mei")
    await asyncio.wait_for(started.wait(), 3)
    pending = rt.running["Mei"]
    assert pending.continuation.summarizing_work
    # A different resident's real repository operation can complete while notes wait.
    work(rt, "Tomas")
    await take(rt, "Tomas", "task-2")
    rt.wall.value += 2
    rt.schedule("Tomas", use("command", command="true"))
    await finish(rt, "Tomas")
    assert not pending.task.done()
    assert rt.now == at(1, "08:00:30")
    assert next(iter(rt.env.providers.values())).commands[-1] == ("Tomas", "true")
    if boundary == "lunch":
        rt.sim.config = rt.sim.config.model_copy(update={"lunch_place": "restaurant"})
        rt.now = at(1, "12:00")
        rt.daily_choices()
    else:
        rt.now = at(1, "22:00")
        rt.boundary()
    await asyncio.gather(pending.task, return_exceptions=True)
    await rt.refresh_decisions()
    rt.flush_leaves()
    rt.daily_choices()
    assert pending.task.cancelled()
    assert not pending.continuation.committed
    assert resident.memory.work.pending_scopes(pending.activity)
    assert not resident.memory.work.summaries("task-1")
    assert rt.current.get("Mei") != pending.activity
    if boundary == "lunch":
        assert rt.activities[rt.current["Mei"]].kind == "move"
    release.set()
    # Nightly catch-up can still cover the original receipt after forced departure.
    await resident.summarize_work(rt.now // 60)
    assert not resident.memory.work.pending_scopes(pending.activity)
    assert resident.memory.work.summaries("task-1")


@pytest.mark.parametrize("exit_kind", ["leave", "rest"])
async def test_long_work_exit_is_one_summary_before_original_transition(
    rt,  # noqa: F811
    tmp_path,
    exit_kind,
):
    started, release = asyncio.Event(), asyncio.Event()
    requests = []

    class Client:
        async def complete(self, request):
            requests.append(request)
            if request.metadata["purpose"] == "work_summary":
                started.set()
                await release.wait()
                return await ScriptedClient(lambda _: {"summary": "One bounded result."}).complete(
                    request
                )
            answer = (
                {"thought": "Leave now", "do": "leave this activity"}
                if exit_kind == "leave"
                else {
                    "thought": "Rest now",
                    "do": "rest",
                    "day": "today",
                    "until": "12:00",
                    "wake for invitations": True,
                }
            )
            return await ScriptedClient(lambda _: answer).complete(request)

    resident = Agent.create(
        tmp_path / "resident",
        SEED,
        Client(),
        CognitionConfig(work_notes=WorkNotesConfig(enabled=True)),
        TOWN,
    )
    rt.sim.agents["Mei"] = resident
    active = work(rt)
    await take(rt)
    resident.memory.work.begin_activity(active.id, "task-1", rt.now // 60)
    for number in range(1, 81):
        resident.perceive(
            [
                Percept(
                    seq=10000 + number,
                    time=rt.now // 60,
                    kind=EventKind.COMMAND_EXECUTED,
                    task_id="task-1",
                    activity_id=active.id,
                    text=f"operation {number}: " + "x" * 1500,
                )
            ]
        )
    rt.start_decision("Mei")
    await asyncio.wait_for(started.wait(), 3)
    pending = rt.running["Mei"]
    assert rt.current["Mei"] == active.id and pending.continuation.summarizing_work
    assert not resident.memory.work.summaries("task-1")
    resident.perceive(
        [
            Percept(
                seq=20000,
                time=rt.now // 60,
                kind=EventKind.COMMAND_EXECUTED,
                task_id="task-1",
                activity_id=active.id,
                text="ARRIVED_AFTER_SCOPE",
            )
        ]
    )
    late_entry = resident.memory.work.entries("task-1")[-1]["entry"]
    # One slow model call advances the shared 15x wall clock; it cannot cause
    # a chain of 6000-character chunks and repeated merges.
    rt.wall.value += 40
    release.set()
    await finish(rt, "Mei")
    assert rt.now == at(1, "08:10")
    if "Mei" in rt.running:
        await finish(rt, "Mei")
    rt.flush_leaves()
    assert rt.current.get("Mei") != active.id
    summaries = resident.memory.work.summaries("task-1")
    assert len(summaries) == 1 and len(summaries[0]["text"]) <= 1600
    assert late_entry not in summaries[0]["source_entries"]
    purposes = [r.metadata["purpose"] for r in requests]
    assert purposes.count("work_summary") == 1 and "work_summary_merge" not in purposes
    if exit_kind == "rest":
        assert rt.activities[rt.current["Mei"]].kind == "rest"


async def test_work_without_job_operations_exits_without_summary(
    rt,  # noqa: F811
    tmp_path,
):
    requests = []

    def answer(request):
        requests.append(request)
        assert not request.metadata["purpose"].startswith("work_summary")
        return {"thought": "End research", "do": "leave this activity"}

    resident = Agent.create(
        tmp_path / "resident",
        SEED,
        ScriptedClient(answer),
        CognitionConfig(work_notes=WorkNotesConfig(enabled=True)),
        TOWN,
    )
    rt.sim.agents["Mei"] = resident
    active = work(rt)
    rt.start_decision("Mei")
    await finish(rt, "Mei")
    if "Mei" in rt.running:
        await finish(rt, "Mei")
    rt.flush_leaves()
    assert rt.current.get("Mei") != active.id
    assert requests and not resident.memory.work.tasks()


async def test_real_work_claim_and_command_are_scoped_before_agent_exit(
    rt,  # noqa: F811
    tmp_path,
):
    import json

    actions = iter(
        [
            {"thought": "Begin work", "do": "work", "public": False},
            {"thought": "Take this job", "do": "take a job", "job": "task-1", "partner": None},
            {"thought": "Check the repository", "do": "run a command", "command": "true"},
            {"thought": "Leave now", "do": "leave this activity"},
        ]
    )
    requests = []

    def answer(request):
        requests.append(request)
        if request.metadata["purpose"] == "work_summary":
            return {"summary": "The controlled repository check returned its recorded result."}
        return next(actions)

    resident = Agent.create(
        tmp_path / "resident",
        SEED,
        ScriptedClient(answer),
        CognitionConfig(work_notes=WorkNotesConfig(enabled=True)),
        TOWN,
    )
    rt.sim.agents["Mei"] = resident
    rt.env.move("Mei", "workshop", time=rt.now // 60)
    active_id = None
    for step in range(4):
        rt.start_decision("Mei")
        await finish(rt, "Mei")
        if "Mei" in rt.running:
            await finish(rt, "Mei")
        rt.flush_leaves()
        if step == 0:
            active_id = rt.current["Mei"]
    assert rt.current.get("Mei") != active_id
    notes = resident.memory.work
    entries = notes.entries("task-1")
    assert any(e["type"] == "activity" and e["activity_id"] == active_id for e in entries)
    commands = [e for e in entries if e.get("kind") == "command_executed"]
    assert len(commands) == 1 and commands[0]["activity_id"] == active_id
    summary = notes.summaries("task-1")
    assert len(summary) == 1 and summary[0]["activity_id"] == active_id
    assert commands[0]["entry"] in summary[0]["source_entries"]
    assert not notes.pending_scopes(active_id)
    assert [r.metadata["purpose"] for r in requests].count("work_summary") == 1
    provider = next(iter(rt.env.providers.values()))
    assert provider.commands == [("Mei", "true")]
    events = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
    receipt = next(e for e in events if e["kind"] == "command_executed")
    from core.interaction.events import Event

    assert receipt["payload"]["activity"] == active_id
    assert Event.model_validate(receipt).percept("Mei").activity_id == active_id
