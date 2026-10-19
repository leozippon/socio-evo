"""Public client verdicts reach every worker without exposing private checks."""

import pytest

from core.environment import Environment
from core.interaction import CheckWork, ClaimTask, EventKind
from tests.core.environment import test_technical_community as community
from tests.core.environment.test_environment import act, deliver, go

env = community.env


async def joint(env):
    await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben"))
    await act(env, "Ben", ClaimTask(task_id="task-3", partner="Ana"))
    go(env, "house", "Ben")
    for who in env.agents:
        env.perceive(who)


async def test_refusal_reaches_remote_partner_and_compact_context_survives_cursor(env):
    await joint(env)
    result = await act(env, "Ana", deliver("task-3", "bad"))
    submitted = next(e for e in result if e.kind == EventKind.WORK_SUBMITTED)
    assert set(submitted.audience) == {"Ana", "Ben"}
    assert next(e for e in result if e.kind == EventKind.WORK_ASSESSED).audience == ()
    for who in ("Ana", "Ben"):
        percepts = env.perceive(who)
        assert any(p.seq == submitted.seq for p in percepts)
        text = env.status_view(who, include_evidence=False)
        assert "REJECTED — rework required" in text and "submitted by Ana" in text
        assert env.latest_work_results[who].event == submitted.seq
        assert env.perceive(who) == ()
        assert "REJECTED — rework required" in env.status_view(who, include_evidence=False)
    assert not env.latest_work_results.get("Cai")
    assert "Latest completed client verdict" not in env.status_view("Cai")


async def test_rework_acceptance_replaces_old_verdict_even_after_claim_archived(env):
    await joint(env)
    await act(env, "Ana", deliver("task-3", "bad"))
    for who in ("Ana", "Ben"):
        env.perceive(who)
    result = await act(env, "Ben", deliver("task-3", "perfect"), clock="10:10")
    submitted = next(e for e in result if e.kind == EventKind.WORK_SUBMITTED)
    for who in ("Ana", "Ben"):
        assert who in submitted.audience
        assert env.board.claim_of(who) is None
        text = env.status_view(who, include_evidence=False)
        assert "not working on any job" in text
        assert "ACCEPTED" in text and "submitted by Ben" in text
        assert "REJECTED" not in text
        assert env.economy.balances[who] == 145


async def test_private_check_cannot_become_partners_verdict(env):
    await joint(env)
    env.config = env.config.model_copy(update={"strict_acceptance": False})
    result = await act(env, "Ana", CheckWork(task_id="task-3", part=1, solution="bad"))
    checked = next(e for e in result if e.kind == EventKind.WORK_CHECKED)
    assert checked.audience == ("Ana",)
    assert not env.latest_work_results
    assert not env.perceive("Ben")
    assert "Latest completed client verdict" not in env.status_view("Ben")


@pytest.mark.parametrize("solution", ["bad", "perfect"])
async def test_result_checkpoint_restore_keeps_receipts_and_legacy_default(env, solution):
    await joint(env)
    await act(env, "Ana", deliver("task-3", solution))
    for who in ("Ana", "Ben"):
        env.perceive(who)
    saved = env.state()
    restored = Environment.restore(env.config, saved, env.providers, env.log.path)
    for who in ("Ana", "Ben"):
        assert restored.status_view(who, include_evidence=False) == env.status_view(
            who, include_evidence=False
        )
        assert restored.latest_work_results[who].accepted == (solution == "perfect")
    legacy = {k: v for k, v in saved.items() if k != "latest_work_results"}
    assert (
        Environment.restore(env.config, legacy, env.providers, env.log.path).latest_work_results
        == {}
    )


async def test_checking_service_outage_not_recorded_as_a_failed_verdict(env):
    from core.environment.rejection import AssessmentUnavailable

    await joint(env)

    async def unavailable(*args):
        raise AssessmentUnavailable("service temporarily unavailable")

    next(iter(env.providers.values())).assess = unavailable
    result = await act(env, "Ana", deliver("task-3", "patch"))
    assert result[0].kind == EventKind.WORK_DELAYED
    assert set(result[0].audience) == {"Ana", "Ben"}
    assert not env.latest_work_results
