"""Only a resident's own new public client verdict wakes Rest, then leaves a choice."""

import asyncio

import pytest

from core.environment import Assessment, Trade
from core.interaction import ClaimTask, EventKind, SubmitWork
from runtime.activities.model import RestActivity, at
from tests.runtime.activities import test_engine as base
from tests.runtime.activities import test_rest_transitions as transitions

engine = base.engine
scheduler = transitions.scheduler


@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("wake", [True, False])
async def test_background_verdict_wakes_rest_and_preserves_result(scheduler, accepted, wake):
    scheduler.now = at(1, "08:00")
    base.work(scheduler)
    await base.perform(scheduler, "Mei", "claim", job="task-1", partner=None)
    provider = scheduler.env.providers[Trade.PROGRAMMING]
    provider.verdict_ready = asyncio.Event()

    async def assess(part, patch):
        await provider.verdict_ready.wait()
        return Assessment(passed=accepted, quality=float(accepted), feedback="Verdict")

    provider.assess = assess
    await base.perform(scheduler, "Mei", "submit", report="Repair ready")
    scheduler.env.move("Mei", scheduler.env.config.homes["Mei"], time=scheduler.now // 60)
    scheduler.start_rest("Mei", at(1, "11:00"), wake=wake)
    rest = scheduler.activities[scheduler.current["Mei"]]
    scheduler.now = scheduler.assessments["task-1"]["due"]
    await scheduler.assessment("task-1")
    scheduler.wake_rests()
    assert scheduler.current["Mei"] == rest.id  # Pending/delayed checks are not verdicts.
    provider.verdict_ready.set()
    await scheduler.futures["task-1"]
    await scheduler.assessment("task-1")
    notice = scheduler.env.latest_work_results["Mei"]
    assert notice.accepted is accepted
    assert (scheduler.env.board.claim_of("Mei") is None) is accepted
    scheduler.wake_rests()
    assert "Mei" not in scheduler.current
    assert not rest.members["Mei"].active
    assert notice.event in {e.seq for e in scheduler.env.log.pending_events("Mei")}
    observation = scheduler.observation("Mei")
    assert "ACCEPTED" in observation.situation if accepted else "REJECTED" in observation.situation
    assert any(p.seq == notice.event for p in observation.percepts)
    assert observation.allowed  # Reconsider freely; do not start Work or claim another job.
    scheduler.start_rest("Mei", at(1, "11:00"), wake=wake)
    scheduler.wake_rests()
    assert isinstance(scheduler.activities[scheduler.current["Mei"]], RestActivity)


@pytest.mark.parametrize("accepted", [True, False])
async def test_shared_verdict_wakes_both_workers_but_not_bystander(scheduler, accepted):
    scheduler.now = at(1, "08:00")
    env = scheduler.env
    task = next(v.task for v in env.board.listings.values() if v.task.worker_count == 2)
    for who, partner in [("Mei", "Tomas"), ("Tomas", "Mei")]:
        env.move(who, "workshop", time=scheduler.now // 60)
        await env.execute(
            who,
            ClaimTask(task_id=task.id, partner=partner),
            time=scheduler.now // 60,
            scene="activities",
            witnesses=[who],
        )
    for who in ("Mei", "Tomas", "Aisha"):
        env.move(who, "workshop", time=scheduler.now // 60)
        scheduler.start_rest(who, at(1, "11:00"), wake=False)
    scheduler.now += 60
    await env._submit(
        "Mei",
        SubmitWork(task_id=task.id, solution="patch", report="Ready"),
        time=scheduler.now // 60,
        place="workshop",
        scene="activities",
        prepared=(
            "patch",
            Assessment(passed=accepted, quality=float(accepted), feedback="Verdict"),
        ),
    )
    [verdict] = [r for r in env.log.pending_events("Mei") if r.kind == EventKind.WORK_SUBMITTED]
    assert ("Aisha" in verdict.audience) is accepted
    scheduler.wake_rests()
    assert "Mei" not in scheduler.current and "Tomas" not in scheduler.current
    assert isinstance(scheduler.activities[scheduler.current["Aisha"]], RestActivity)
    assert all(verdict.seq in {e.seq for e in env.log.pending_events(w)} for w in ("Mei", "Tomas"))


def test_pending_hidden_and_unrelated_events_do_not_wake_rest(scheduler):
    scheduler.start_rest("Mei", at(1, "11:00"), wake=False)
    for kind in (
        EventKind.SUBMISSION_PENDING,
        EventKind.WORK_DELAYED,
        EventKind.WORK_ASSESSED,
        EventKind.WORK_SUBMITTED,
    ):
        scheduler.env.emit(
            kind,
            "Other event",
            time=scheduler.now // 60,
            actor="Tomas",
            audience=["Mei"],
            payload={"task_id": "task-1"},
        )
    scheduler.wake_rests()
    assert isinstance(scheduler.activities[scheduler.current["Mei"]], RestActivity)
