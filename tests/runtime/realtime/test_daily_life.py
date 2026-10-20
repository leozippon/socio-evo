import asyncio
import json

from core.interaction import Decision
from runtime.activities.model import MoveActivity, at
from runtime.realtime.engine import Finished, Running
from tests.runtime.activities.test_daily_life import enable
from tests.runtime.realtime import test_engine as realtime_tests
from tests.runtime.realtime.test_engine import choose

engine = realtime_tests.engine
rt = realtime_tests.rt


async def test_noon_discards_old_selection_and_waits_for_started_tool(rt):
    enable(rt)
    who = next(iter(rt.sim.agents))
    rt.now = at(1, "11:59")

    async def old_choice():
        return Finished(
            Decision(thought="sleep", action=choose("select_rest", arguments={"until": "22:00"})),
            at(1, "12:01"),
            1,
        )

    task = asyncio.create_task(old_choice())
    await task
    job = Running(task, "decision", None, rt.now)
    rt.running[who] = job
    rt.now = at(1, "12:00")
    rt.daily_choices()
    assert who not in rt.current
    rt.now = at(1, "12:01")
    await rt.finish(who, job)
    rt.daily_choices()
    assert isinstance(rt.activities[rt.current[who]], MoveActivity)


async def test_lunch_drains_other_speaker_without_waiting_for_joint_idle(rt):
    from tests.runtime.realtime.test_engine import conversation, use

    enable(rt)
    rt.now = at(1, "11:59")
    activity = conversation(rt)
    gate = asyncio.Event()

    async def utterance():
        await gate.wait()
        return Finished(
            Decision(thought="finish sentence", action=use("reply", text="See you at lunch.")),
            at(1, "12:01"),
            1,
        )

    task = asyncio.create_task(utterance())
    job = Running(task, "decision", activity.id, rt.now)
    rt.running["Tomas"] = job
    rt.now = at(1, "12:00")
    rt.daily_choices()
    assert "Mei" in rt.deferred
    assert activity.id in rt.closing
    assert not task.cancelled()
    gate.set()
    await task
    rt.now = at(1, "12:01")
    await rt.finish("Tomas", job)
    assert activity.messages[-1].text == "See you at lunch."
    rows = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
    speech = next(row for row in rows if row["kind"] == "speech" and row["actor"] == "Tomas")
    assert speech["payload"]["generation_start"] == at(1, "11:59")
    assert speech["payload"]["generation_end"] == at(1, "12:01")
    assert speech["payload"]["generation_wall_seconds"] == 120 / rt.settings.multiplier
    assert any(row["kind"] == "decision" and row["actor"] == "Tomas" for row in rows)
    rt.flush_leaves()
    rt.daily_choices()
    assert all(isinstance(rt.activities[rt.current[who]], MoveActivity) for who in ("Mei", "Tomas"))
