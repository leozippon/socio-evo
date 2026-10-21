"""Work note generation shares decision cancellation, never the town's event loop."""

import asyncio

import pytest

from core.agent import Agent, CognitionConfig
from core.agent.config import WorkNotesConfig
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
    resident.memory.work.record("task-1", rt.now // 60, "observation", "SAVED_RESULT")
    rt.start_decision("Mei")
    await started.wait()
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
    assert resident.memory.work.cursor("task-1") == (0, 0)
    assert rt.current.get("Mei") != pending.activity
    if boundary == "lunch":
        assert rt.activities[rt.current["Mei"]].kind == "move"
    release.set()
    # Nightly catch-up can still cover the original receipt after forced departure.
    await resident.summarize_work(rt.now // 60)
    assert resident.memory.work.cursor("task-1") > (0, 0)
