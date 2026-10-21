"""Voluntary methods, durable edits, observable outcomes and Activity boundaries."""

import asyncio
import json

import pytest

from core.agent import DecisionContinuation
from core.agent.config import ContextBudgetConfig, WorkNotesConfig
from core.agent.evolution.operators import SkillOperator
from core.agent.memory import Record, Skill
from core.agent.personal_skills import feedback_context
from core.agent.prompts import WriteSkill
from core.interaction import EventKind, Percept
from infrastructure.llm import ScriptedClient

METHOD = Skill(
    name="check-first",
    title="Check first",
    description="For repairs.",
    body="METHOD_V1: read the current file before editing.",
)
PASS = {"thought": "I choose freely.", "do": "carry on quietly"}
USE = {"thought": "This may help.", "do": "use skill", "name": "check-first"}


def scoped(observe, kind="work", identifier="work-1", **updates):
    return observe(1).model_copy(
        update={
            "activity_kind": kind,
            "activity_id": identifier,
            "activity_task_id": "task-1" if kind == "work" else None,
            "own_task_id": "task-1",
            "work_activity": kind == "work",
            **updates,
        }
    )


def replies(agent, *answers):
    pending = iter(answers)
    requests = []

    def answer(request):
        requests.append(request)
        return next(pending)

    agent.client = ScriptedClient(answer)
    return requests


@pytest.mark.parametrize("budget", [False, True])
@pytest.mark.parametrize("notes", [False, True])
async def test_choose_execute_feedback_revise_and_reuse(agent, observe, budget, notes):
    agent.cognition = agent.cognition.model_copy(
        update={
            "context_budget": ContextBudgetConfig(enabled=budget),
            "work_notes": WorkNotesConfig(enabled=notes),
        }
    )
    agent.memory.skills.write(METHOD)
    observation = scoped(observe)
    requests = replies(agent, USE, PASS)
    await agent.act(observation)
    assert "METHOD_V1" not in "\n".join(m.content for m in requests[0].messages)
    assert "METHOD_V1" in requests[1].messages[-1].content
    assert len(requests) == 2
    action = next(r for r in agent.memory.episodic.read() if r.action)
    assert action.skill_trace["skill"]["version"] == METHOD.version

    result = Percept(
        seq=10,
        time=observation.time + 1,
        kind=EventKind.WORK_CHECKED,
        actor=agent.id,
        task_id="task-1",
        activity_id="work-1",
        text="Local test failed: the caller uses a different format.",
    )
    change = {
        "change": "write",
        "title": METHOD.title,
        "summary": METHOD.description,
        "text": "METHOD_V2: inspect the caller as well.",
    }
    requests = replies(
        agent,
        {
            "thought": "I missed the caller.",
            "do": "revise skill",
            "change": change,
            "sources": [10],
        },
        PASS,
    )
    await agent.act(observation.model_copy(update={"time": result.time, "percepts": (result,)}))
    assert "Local test failed" in requests[0].messages[-1].content
    assert "METHOD_V2" in requests[1].messages[-1].content
    feedback = next(r for r in agent.memory.episodic.read() if r.seq == 10)
    assert action.decision_id in feedback.related_decisions
    revised = agent.memory.skills.read()[0]
    assert revised.version != METHOD.version
    assert action.skill_trace["skill"]["body"] == METHOD.body
    trace = next(
        r.skill_trace
        for r in agent.memory.episodic.read()
        if r.skill_trace.get("event") == "revised"
    )
    assert trace["sources"] == [10] and trace["before"]["version"] == METHOD.version

    requests = replies(agent, USE, PASS)
    await agent.act(scoped(observe, identifier="work-2", time=result.time + 1, percepts=()))
    assert "METHOD_V1" not in requests[0].messages[-1].content
    assert "METHOD_V2" not in requests[0].messages[-1].content
    assert "METHOD_V2" in requests[1].messages[-1].content
    review = feedback_context(agent.memory, result.time + 2)
    assert "METHOD_V1" in review and "Local test failed" in review
    assert all(r.metadata["purpose"] == "act" for r in requests)


@pytest.mark.parametrize("kind", ["selection", "conversation", "rest", "move"])
@pytest.mark.parametrize("budget", [False, True])
async def test_nonwork_context_keeps_social_news_without_old_code_or_reasons(
    agent, observe, kind, budget
):
    agent.cognition = agent.cognition.model_copy(
        update={
            "context_budget": ContextBudgetConfig(enabled=budget),
            "work_notes": WorkNotesConfig(enabled=True),
        }
    )
    agent.memory.skills.write(METHOD)
    work = scoped(observe)
    requests = replies(agent, USE, PASS)
    await agent.act(work)
    agent.memory.episodic.append(
        [
            Record(time=work.time, text="OLD_DECISION_REASON: never join anyone."),
            Record(
                time=work.time,
                kind=EventKind.COMMAND_EXECUTED,
                task_id="task-1",
                text="OLD_CODE_123",
            ),
        ]
    )
    agent.memory.work.save_summary("task-1", work.time, "OLD_JOB_SUMMARY", (0, 0), (0, 1))
    news = Percept(
        seq=100,
        time=work.time + 1,
        kind=EventKind.SPEECH,
        activity_id="conversation-3",
        text="Ben: You can join our lunch conversation.",
    )
    requests = replies(agent, PASS)
    await agent.act(
        scoped(
            observe,
            kind,
            None if kind == "selection" else kind + "-3",
            time=news.time,
            percepts=(news,),
        )
    )
    prompt = "\n".join(m.content for m in requests[0].messages)
    for marker in ("OLD_CODE_123", "OLD_JOB_SUMMARY", "OLD_DECISION_REASON", "METHOD_V1"):
        assert marker not in prompt
    assert "join our lunch conversation" in prompt
    assert agent.personal_skills.selected is None
    assert len(requests) == 1  # No mandatory reflection or skill operation.


async def test_edit_survives_interruption_without_committing_an_external_action(agent, observe):
    continuation = DecisionContinuation()
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "thought": "Save the experience.",
                "do": "revise skill",
                "sources": [1],
                "change": {
                    "change": "write",
                    "title": METHOD.title,
                    "summary": METHOD.description,
                    "text": METHOD.body,
                },
            }
        raise asyncio.CancelledError

    agent.client = ScriptedClient(respond)
    with pytest.raises(asyncio.CancelledError):
        await agent.act(scoped(observe), continuation=continuation)
    assert agent.memory.skills.read() == [METHOD]
    assert not any(r.action for r in agent.memory.episodic.read())
    requests = replies(agent, PASS)
    await agent.act(scoped(observe, "selection", None), continuation=continuation)
    continuation.commit()
    assert (
        len([r for r in agent.memory.episodic.read() if r.skill_trace.get("event") == "revised"])
        == 1
    )
    assert all(m.role != "assistant" for m in requests[0].messages)


async def test_invalid_names_and_unwitnessed_sources_are_bounded(agent, observe):
    requests = replies(
        agent,
        {**USE, "name": "someone-elses-skill"},
        {
            "thought": "Unseen result.",
            "do": "revise skill",
            "sources": [999],
            "change": {
                "change": "write",
                "title": METHOD.title,
                "summary": METHOD.description,
                "text": METHOD.body,
            },
        },
        {**USE, "name": None},
        PASS,
    )
    await agent.act(scoped(observe))
    assert "No such skill" in requests[1].messages[-1].content
    assert "must be an event you have witnessed" in requests[2].messages[-1].content
    assert "use skill" not in json.dumps(requests[-1].json_schema)
    assert "revise skill" not in json.dumps(requests[-1].json_schema)
    assert not agent.memory.skills.read()


async def test_night_and_day_share_updates_and_retirement_clears_binding(agent, observe):
    agent.memory.skills.write(METHOD)
    replies(agent, USE, PASS)
    await agent.act(scoped(observe))
    SkillOperator.file(
        agent,
        [
            WriteSkill(
                change="write", title=METHOD.title, summary="Updated at night", text="METHOD_V3"
            )
        ],
        time=1000,
    )
    assert agent.personal_skills.selected.body == "METHOD_V3"
    requests = replies(
        agent,
        {
            "thought": "No longer helpful.",
            "do": "revise skill",
            "change": {"change": "take out", "title": METHOD.title},
        },
        PASS,
    )
    await agent.act(scoped(observe, time=1001))
    assert not agent.memory.skills.read() and agent.personal_skills.selected is None
    assert "Your selected method for this Activity" not in requests[-1].messages[-1].content


async def test_create_select_and_clear_removes_body_even_with_usage_history(agent, observe):
    requests = replies(
        agent,
        {
            "thought": "Keep this method.",
            "do": "revise skill",
            "sources": [1],
            "change": {
                "change": "write",
                "title": METHOD.title,
                "summary": METHOD.description,
                "text": METHOD.body,
            },
        },
        USE,
        PASS,
    )
    await agent.act(scoped(observe))
    assert "check-first" in requests[1].messages[0].content
    assert "METHOD_V1" not in requests[1].messages[-1].content
    assert "METHOD_V1" in requests[2].messages[-1].content
    requests = replies(agent, {**USE, "name": None}, PASS)
    await agent.act(scoped(observe, percepts=()))
    assert "METHOD_V1" in requests[0].messages[-1].content
    assert "METHOD_V1" not in requests[1].messages[-1].content
    assert agent.personal_skills.selected is None


def test_skill_paths_cannot_escape_private_library(agent, tmp_path):
    other = tmp_path / "other.md"
    other.write_text("PRIVATE")
    agent.memory.skills.directory.mkdir()
    (agent.memory.skills.directory / "check-first.md").symlink_to(other)
    with pytest.raises(ValueError, match="Symlinked"):
        agent.memory.skills.write(METHOD)
    with pytest.raises(ValueError, match="Invalid"):
        agent.memory.skills.remove("../../other")
    assert other.read_text() == "PRIVATE"
