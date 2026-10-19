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


@pytest.fixture
def immediate(env):
    env.config = env.config.model_copy(update={"replacement_timing": "immediate"})
    return env


async def test_success_immediately_replaces_solo_publicly_without_priority(immediate):
    env = immediate
    original = env.board.listings["task-1"].task
    await act(env, "Ana", ClaimTask(task_id=original.id))
    events = await act(env, "Ana", deliver(original.id, "perfect"))
    [posted] = [e for e in events if e.kind == EventKind.TASK_POSTED]
    task = env.board.listings[posted.payload["task"]["id"]].task
    assert posted.time == next(e.time for e in events if e.kind == EventKind.WORK_ASSESSED)
    assert task.worker_count == 1 and task.parts[0].reference != original.parts[0].reference
    assert set(posted.audience) == set(AGENTS)
    assert env.board.claim_of("Ana") is None
    assert original.id not in env.board.listings and original.id not in env.board.claims
    assert env.post(time_at(2, "08:00"), 0) == []
    await act(env, "Ben", ClaimTask(task_id=task.id))
    assert env.board.claim_of("Ben").task.id == task.id
    lost = await act(env, "Ana", ClaimTask(task_id=task.id))
    assert lost[0].kind == EventKind.ACTION_REJECTED


async def test_joint_replacement_requires_same_workers_and_only_on_pass(immediate):
    env = immediate
    await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben"))
    await act(env, "Ben", ClaimTask(task_id="task-3", partner="Ana"))
    failed = await act(env, "Ana", deliver("task-3", "bad"))
    assert not any(e.kind == EventKind.TASK_POSTED for e in failed)
    assert len(env.board.listings) == 2 and "task-3" in env.board.claims
    passed = await act(env, "Ben", deliver("task-3", "perfect"))
    [posted] = [e for e in passed if e.kind == EventKind.TASK_POSTED]
    assert posted.payload["task"]["required_workers"] == 2
    assert len(posted.payload["task"]["parts"]) == 1
    assert len([e for e in passed if e.kind == EventKind.PAYMENT]) == 2
    assert len(env.board.listings) == 3
    assert env.post(time_at(2, "08:00"), 0) == []
    duplicate = await act(env, "Ben", deliver("task-3", "perfect"))
    assert duplicate[0].kind == EventKind.ACTION_REJECTED
    assert len(env.board.listings) == 3


async def test_expiry_reopens_original_but_retired_notices_get_same_type_replacement(immediate):
    env = immediate
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    before = env.board.next_number
    events = env.start_day(time_at(4, "07:00"), random.Random(0))
    assert "task-1" in env.board.listings
    assert env.board.next_number == before
    assert not any(e.kind == EventKind.TASK_POSTED for e in events)
    env.config = env.config.model_copy(update={"task_shelf_life_days": 1})
    events = env.start_day(time_at(6, "07:00"), random.Random(0))
    retired = [e for e in events if e.kind == EventKind.TASK_RETIRED]
    posted = [e for e in events if e.kind == EventKind.TASK_POSTED]
    assert len(retired) == len(posted) == 3
    assert sorted(e.payload["task"]["required_workers"] for e in posted) == [1, 1, 2]
    assert all(e.time == time_at(6, "07:00") for e in posted)
    assert env.post(time_at(6, "08:00"), 0) == []


async def test_exhausted_pool_is_reported_without_reusing_issue(immediate):
    env = immediate
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    trade = next(iter(env.providers))
    env.board.issued_references[trade.value] = [str(n) for n in range(30)]
    events = await act(env, "Ana", deliver("task-1", "perfect"))
    assert not any(e.kind == EventKind.TASK_POSTED for e in events)
    assert any(e.kind == "task_replacement_unavailable" for e in events)
    assert env.board.claim_of("Ana") is None
    assert len(env.board.listings) == 2


async def test_assessment_service_outage_does_not_replace_job(immediate):
    env = immediate
    await act(env, "Ana", ClaimTask(task_id="task-1"))

    async def unavailable(*args):
        raise AssessmentUnavailable("temporary outage")

    env.providers[next(iter(env.providers))].assess = unavailable
    events = await act(env, "Ana", deliver("task-1", "perfect"))
    assert [e.kind for e in events] == [EventKind.WORK_DELAYED]
    assert env.board.claim_of("Ana").task.id == "task-1"
    assert len(env.board.listings) == 2


async def test_immediate_timing_does_not_change_append_mode(env):
    env.config = env.config.model_copy(
        update={"posting_mode": "append", "replacement_timing": "immediate"}
    )
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    events = await act(env, "Ana", deliver("task-1", "perfect"))
    assert not any(e.kind == EventKind.TASK_POSTED for e in events)


async def test_legacy_multipart_job_replaced_only_after_all_parts_pass(env):
    config = env.config.model_copy(update={"replacement_timing": "immediate"})
    other = Environment.create(config, AGENTS, Provider(), env.log.path.parent / "multi.jsonl")
    other.post(time_at(1, "08:00"), 0)
    go(other, "office", *AGENTS)
    await act(other, "Ana", ClaimTask(task_id="task-3", partner="Ben", part=1))
    await act(other, "Ben", ClaimTask(task_id="task-3"))
    partial = await act(other, "Ana", deliver("task-3", "perfect", part=1))
    assert not any(e.kind == EventKind.TASK_POSTED for e in partial)
    assert "task-3" in other.board.claims
    final = await act(other, "Ben", deliver("task-3", "perfect", part=2))
    [posted] = [e for e in final if e.kind == EventKind.TASK_POSTED]
    replacement = other.board.listings[posted.payload["task"]["id"]].task
    assert replacement.worker_count == 2
    assert len(replacement.parts) == 2


async def test_unready_replacement_does_not_undo_successful_acceptance(immediate, monkeypatch):
    from core.environment.rejection import TaskUnavailable

    env = immediate
    await act(env, "Ana", ClaimTask(task_id="task-1"))

    def not_ready(*args):
        raise TaskUnavailable("missing cached environment metadata")

    monkeypatch.setattr(next(iter(env.providers.values())), "sample_available", not_ready)
    events = await act(env, "Ana", deliver("task-1", "perfect"))
    assert env.board.claim_of("Ana") is None
    assert len([e for e in events if e.kind == EventKind.PAYMENT]) == 1
    [held] = [e for e in events if e.kind == EventKind.TASK_REPLACEMENT_UNAVAILABLE]
    assert held.payload["reason"] == "environment_unready"
    assert not any(e.kind == EventKind.TASK_POSTED for e in events)
