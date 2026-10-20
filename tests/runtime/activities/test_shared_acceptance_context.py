"""Activity selection pins shared verdicts even after delivery cursors advance."""

import asyncio

import pytest

from core.environment import Assessment
from core.interaction import ClaimTask
from tests.core.environment.test_environment import act
from tests.runtime.activities import test_engine as base
from tests.runtime.realtime.test_engine import rt as rt

engine = base.engine


@pytest.fixture(params=["engine", "rt"])
def scheduler(request):
    return request.getfixturevalue(request.param)


async def test_shared_failed_verdict_is_current_in_work_rest_and_selection(scheduler):
    e = scheduler
    base.work(e, "Mei")
    base.work(e, "Tomas")
    await act(e.env, "Mei", ClaimTask(task_id="task-7", partner="Tomas"))
    await act(e.env, "Tomas", ClaimTask(task_id="task-7", partner="Mei"))
    await base.agree_team(e)
    provider = next(iter(e.env.providers.values()))

    async def failed(*args):
        return Assessment(passed=False, quality=0, feedback="Client regression check failed")

    provider.assess = failed
    await e.submit("Mei", "Shared repair")
    await asyncio.sleep(0)
    e.now += e.timing.assessment_seconds
    await e.assessment("task-7")
    assert "task-7" not in e.assessments
    for who in ("Mei", "Tomas"):
        assert any("regression check failed" in p.text for p in e.env.perceive(who))
        obs = e.observation(who)
        assert "REJECTED — rework required" in obs.situation
        assert "submitted by Mei" in obs.situation
        assert "awaiting background acceptance" not in e.current_facts(who)
    e.leave("Tomas", "Take a break")
    e.select("Tomas", base.choose("select_rest", arguments={"until": "10:00"}))
    assert "REJECTED — rework required" in e.observation("Tomas").situation
    e.leave("Tomas", "Rework")
    assert "REJECTED — rework required" in e.observation("Tomas").situation
    # A newer submission has a different current state from the last completed verdict.
    base.work(e, "Mei")
    await e.submit("Mei", "A revised repair")
    assert "awaiting background acceptance" in e.assessment_waiting("Tomas")
    obs = e.observation("Tomas")
    assert "Latest completed client verdict" in obs.situation
    assert "awaiting background acceptance" in obs.situation
    await e.close()
