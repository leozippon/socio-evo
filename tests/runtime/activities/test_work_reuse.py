"""Vacant/foreign public sessions cannot lock a resident out of their current work place."""

import pytest

from core.environment.rejection import Rejected
from core.interaction import ClaimTask
from runtime.activities.model import WorkActivity, at
from tests.runtime.activities import test_early_arrival as arrival_tests
from tests.runtime.activities import test_engine as activity_tests

gate = arrival_tests.gate
engine = activity_tests.engine
choose = activity_tests.choose


async def posted_job(gate, who="Jonas", partner=None, job="task-1"):
    await gate.env.execute(
        who,
        ClaimTask(task_id=job, partner=partner),
        time=gate.now // 60,
        scene="activities",
        witnesses=[],
    )
    if partner:
        await gate.env.execute(
            partner,
            ClaimTask(task_id=job, partner=who),
            time=gate.now // 60,
            scene="activities",
            witnesses=[],
        )
    if partner:
        await activity_tests.agree_team(gate, resume=False)
    return gate.env.board.claim_of(who)


async def old_home_work(gate):
    gate.now = at(1, "07:04")
    gate.select("Jonas", choose("select_work", seconds=3600, arguments={"public": True}))
    old = gate.activities[gate.current["Jonas"]]
    claim = await posted_job(gate)
    gate.menu("Jonas")  # bind task exactly as in the normal post-claim observation
    assert old.task_id == claim.task.id
    gate.leave("Jonas", "Pause before opening")
    gate.now = at(1, "08:00")
    gate.env.move("Jonas", "workshop", time=gate.now // 60)
    return old, claim


async def test_jonas_home_session_does_not_block_workshop_work(gate):
    old, claim = await old_home_work(gate)
    provider = next(iter(gate.env.providers.values()))
    provider.patches[("Jonas", claim.task.id)] = "existing repository progress"
    gate.select("Jonas", choose("select_work", seconds=1800))
    current = gate.activities[gate.current["Jonas"]]
    assert current.place == "workshop" and current.id != old.id
    assert current.task_id == claim.task.id
    assert not old.participants and old.status == "paused"
    assert provider.patches[("Jonas", claim.task.id)] == "existing repository progress"


async def test_resume_vacant_own_work_relocates_without_resetting_it(gate):
    old, claim = await old_home_work(gate)
    old.history.append({"feedback": "Keep the earlier evidence"})
    assert old.id in gate.menu("Jonas")["work"]
    gate.select("Jonas", choose("resume_work", target=old.id, seconds=1800))
    assert gate.current["Jonas"] == old.id
    assert old.place == "workshop" and old.task_id == claim.task.id
    assert old.history == [{"feedback": "Keep the earlier evidence"}]
    assert old.participants == ("Jonas",)


async def test_local_session_is_preferred_over_first_foreign_match(gate):
    old, claim = await old_home_work(gate)
    local = WorkActivity(
        id="local",
        place="workshop",
        start=gate.now,
        latest_end=gate.end,
        task_id=claim.task.id,
        public=True,
    )
    gate.enter(local, "Jonas", gate.now + 1800)
    gate.leave("Jonas", "Pause briefly")
    gate.select("Jonas", choose("select_work", seconds=1800))
    assert gate.current["Jonas"] == local.id
    assert old.place == gate.env.config.homes["Jonas"]


async def test_active_partner_session_cannot_be_relocated(gate):
    gate.now = at(1, "08:00")
    claim = await posted_job(gate, "Mei", "Tomas", "task-7")
    assert claim is not None
    gate.env.move("Mei", "workshop", time=gate.now // 60)
    gate.select("Mei", choose("select_work", seconds=3600, arguments={"public": True}))
    shared = gate.activities[gate.current["Mei"]]
    shared.task_id = claim.task.id
    gate.env.move("Tomas", "library", time=gate.now // 60)
    with pytest.raises(Rejected, match="active work's location"):
        gate.select("Tomas", choose("resume_work", target=shared.id, seconds=1800))
    assert shared.place == "workshop" and shared.participants == ("Mei",)
    # Independent work elsewhere is legal; explicit joining still requires travel.
    gate.select("Tomas", choose("select_work", seconds=1800))
    assert gate.activities[gate.current["Tomas"]].place == "library"
    gate.leave("Tomas", "Join partner instead")
    gate.env.move("Tomas", "workshop", time=gate.now // 60)
    gate.select("Tomas", choose("resume_work", target=shared.id, seconds=1800))
    assert set(shared.participants) == {"Mei", "Tomas"}


async def test_foreign_ended_activity_cannot_be_resumed(gate):
    old, _ = await old_home_work(gate)
    old.status = "ended"
    with pytest.raises(Rejected, match="resume"):
        gate.select("Jonas", choose("resume_work", target=old.id, seconds=1800))


async def test_active_local_partner_session_has_priority_over_vacant_own_session(gate):
    gate.now = at(1, "08:00")
    await posted_job(gate, "Mei", "Tomas", "task-7")
    for who in ("Mei", "Tomas"):
        gate.env.move(who, "workshop", time=gate.now // 60)
    gate.select("Tomas", choose("select_work", seconds=1800, arguments={"public": True}))
    vacant = gate.activities[gate.current["Tomas"]]
    gate.leave("Tomas", "Pause")
    gate.select("Mei", choose("select_work", seconds=1800, arguments={"public": True}))
    live = gate.activities[gate.current["Mei"]]
    assert live.id != vacant.id
    gate.select("Tomas", choose("select_work", seconds=1800))
    assert gate.current["Tomas"] == live.id
    assert set(live.participants) == {"Mei", "Tomas"}
