"""A joint repair has two workers but one verdict; only completed stock is replaced."""

import random

import pytest

from core.environment import Environment, Part
from core.environment.rejection import AssessmentUnavailable
from core.interaction import ClaimTask, EventKind, time_at
from runtime.scenes.work import WorkSession
from tests.core.environment.test_environment import (
    AGENTS,
    Provider,
    act,
    deliver,
    go,
    make_config,
)


class RepositoryProvider(Provider):
    community = True

    def sample_available(self, rng, workers, issued):
        remaining = sorted(set(range(30)) - {int(i) for i in issued})
        if not remaining:
            return ()
        instance = str(rng.choice(remaining))
        return (
            Part(
                title=f"Repair {instance}",
                specification="Repair the repository.",
                reward=60,
                deadline_days=2,
                reference=instance,
            ),
        )


@pytest.fixture
def env(tmp_path):
    config = make_config().model_copy(
        update={
            "posting_mode": "replenish",
            "strict_acceptance": True,
            "task_shelf_life_days": None,
        }
    )
    result = Environment.create(config, AGENTS, RepositoryProvider(), tmp_path / "events.jsonl")
    result.post(time_at(1, "08:00"), 0)
    go(result, "office", *AGENTS)
    return result


async def test_replenish_completed_only_with_claims_and_expiry(env):
    original = {k: v.task.parts[0].reference for k, v in env.board.listings.items()}
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    await act(env, "Ben", ClaimTask(task_id="task-2"))
    await act(env, "Ana", deliver("task-1", "perfect"))
    added = env.post(time_at(2, "08:00"), 0)
    assert len(added) == 1
    assert added[0].payload["task"]["parts"][0]["reference"] not in original.values()
    assert len(env.board.claims) == 1 and len(env.board.listings) == 2
    env.start_day(time_at(4, "07:00"), random.Random(0))
    assert not env.board.claims
    assert env.board.listings["task-2"].task.parts[0].reference == original["task-2"]
    assert env.post(time_at(4, "08:00"), 0) == []
    env.start_day(time_at(10, "07:00"), random.Random(0))
    assert len(env.board.listings) == 3  # no unclaimed notice retirement


async def test_joint_one_issue_either_partner_submits_one_patch_and_both_paid(env):
    task = env.board.listings["task-3"].task
    assert task.worker_count == 2 and len(task.parts) == 1
    await act(env, "Ana", ClaimTask(task_id=task.id, partner="Ben"))
    assert env.board.claim_of("Ana") is None
    await act(env, "Ben", ClaimTask(task_id=task.id, partner="Ana"))
    claim = env.board.claim_of("Ana")
    assert claim.workers == ("Ana", "Ben") and not claim.parts
    rejected = await act(env, "Ana", ClaimTask(task_id="task-1"))
    assert rejected[0].kind == EventKind.ACTION_REJECTED
    failed = await act(env, "Ben", deliver(task.id, "bad", declaration="incomplete"))
    assert not next(e for e in failed if e.kind == EventKind.WORK_SUBMITTED).payload["accepted"]
    assert env.economy.balances["Ana"] == env.economy.balances["Ben"] == 100
    passed = await act(env, "Ben", deliver(task.id, "perfect", declaration="incomplete"))
    reported = next(e for e in passed if e.kind == EventKind.WORK_SUBMITTED)
    assert reported.payload["declaration"] == "incomplete"  # never rewrite the resident's claim
    assert env.board.claim_of("Ana") is None and env.board.claim_of("Ben") is None
    assert env.economy.balances["Ana"] == env.economy.balances["Ben"] == 145
    assert len([e for e in passed if e.kind == EventKind.PAYMENT]) == 2
    replacement = env.post(time_at(2, "08:00"), 0)
    assert len(replacement) == 1 and replacement[0].payload["task"]["required_workers"] == 2


async def test_grading_outage_is_retryable_not_failed_work_and_compensates_once(env):
    await act(env, "Ana", ClaimTask(task_id="task-1"))

    async def unavailable(*args):
        raise AssessmentUnavailable("service failed")

    env.providers[next(iter(env.providers))].assess = unavailable
    for _ in range(2):
        events = await act(env, "Ana", deliver("task-1", "patch"))
        assert [e.kind for e in events] == [EventKind.WORK_DELAYED]
        assert events[0].percept("Ana").task_id == "task-1"
    claim = env.board.claim_of("Ana")
    assert claim.due_day == 3 and claim.trials == () and claim.deliveries == ()
    assert env.economy.balances["Ana"] == 100


def test_restore_keeps_issued_pool_and_shared_task_schema(env, tmp_path):
    state = env.state()
    restored = Environment.restore(env.config, state, RepositoryProvider(), env.log.path)
    assert restored.state() == state
    assert restored.post(time_at(2, "08:00"), 0) == []
    assert restored.board.listings["task-3"].task.worker_count == 2


def test_shared_invitation_has_no_artificial_part_selection(env):
    session = WorkSession(
        env,
        "scene",
        "office",
        AGENTS,
        start=time_at(1, "08:00"),
        until=time_at(1, "10:30"),
        rounds=3,
        closes=True,
    )
    from core.interaction import Card

    card = Card(session.allowed("Ana"))
    schema = card.model.model_json_schema()
    forms = schema.get("$defs", {}).values()
    invitations = [
        f
        for f in forms
        if f.get("properties", {}).get("do", {}).get("const") == "take a job for two"
    ]
    assert invitations and all("part" not in f["properties"] for f in invitations)
