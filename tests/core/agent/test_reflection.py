"""Private reflection owns a fixed witnessed scope and files each result once."""

import asyncio

import pytest

from core.agent.config import WorkNotesConfig
from core.agent.reflection import _entries
from core.interaction import EventKind, Percept, time_at
from infrastructure.llm import ScriptedClient, StructuredOutputError


def seen(agent, text="A witnessed result", seq=1, time=None, activity="chat", visit="speaker"):
    agent.perceive(
        [
            Percept(
                seq=seq,
                time=time or time_at(1, "12:00"),
                kind=EventKind.SPEECH,
                text=text,
                activity_id=activity,
                activity_visit_id=visit,
            )
        ]
    )


async def test_same_work_activity_two_visits_are_independent(agent):
    agent.cognition = agent.cognition.model_copy(
        update={"work_notes": WorkNotesConfig(enabled=True)}
    )
    notes = agent.memory.work
    requests = []
    agent.client = ScriptedClient(lambda r: requests.append(r) or {"summary": "Visit result."})
    for index, visit in enumerate(("first", "second")):
        notes.begin_activity("work", "task-1", 1 + index, visit_id=visit)
        notes.observe(
            Percept(
                seq=index + 1,
                time=2 + index,
                kind=EventKind.COMMAND_EXECUTED,
                task_id="task-1",
                text=visit,
                activity_id="work",
                activity_visit_id=visit,
            )
        )
        await agent.reflect(20 + index, mode="summary", activity_id="work", visit_id=visit)
    assert len(requests) == 2
    assert "second" not in requests[0].messages[-1].content
    assert "first" not in requests[1].messages[-1].content
    assert [e["visit_id"] for e in notes.summaries("task-1")] == ["first", "second"]


async def test_experience_can_leave_unchanged_and_reads_exact_owned_source(agent):
    seen(agent)
    replies = iter(
        [
            {"do": "read source", "entry": 1, "offset": 2},
            {"reflection": "I will keep considering the evidence.", "sources": [1]},
        ]
    )
    requests = []
    agent.client = ScriptedClient(lambda r: requests.append(r) or next(replies))
    result = await agent.reflect(
        time_at(1, "13:00"),
        mode="experience",
        activity_id="chat",
        visit_id="mine",
        reflection_id="reflection-1",
    )
    assert result["status"] == "completed"
    assert (
        len(requests) == 2
        and "Requested source entry 1, character 2" in requests[1].messages[-1].content
    )
    assert agent.memory.insights.read() == [] and agent.memory.skills.read() == []
    assert agent.reflection_sources("reflection-1").endswith("A witnessed result")
    await agent.reflect(
        time_at(1, "14:00"),
        mode="experience",
        activity_id="chat",
        visit_id="mine",
        reflection_id="reflection-1",
    )
    assert len(requests) == 2


async def test_experience_revises_insight_and_skill_once_with_owned_sources(agent):
    seen(agent)
    agent.client = ScriptedClient(
        lambda _: {
            "reflection": "This suggests a careful check before editing.",
            "sources": [1],
            "insights": [{"change": "add", "belief": "A local check can reveal a mismatch."}],
            "skills": [
                {
                    "change": "write",
                    "title": "Check first",
                    "summary": "Before editing",
                    "text": "Inspect the observed result before choosing a change.",
                }
            ],
        }
    )
    for _ in range(2):
        await agent.reflect(
            time_at(1, "13:00"), mode="experience", activity_id="chat", reflection_id="one"
        )
    assert len(agent.memory.insights.read()) == 1
    assert len(agent.memory.skills.read()) == 1
    changes = [r for r in agent.memory.episodic.read() if r.skill_trace.get("event") == "revised"]
    assert len(changes) == 1 and changes[0].skill_trace["sources"] == [1]
    assert any(r.seq == 1 and r.text == "A witnessed result" for r in agent.memory.episodic.read())


async def test_invalid_source_cannot_commit_any_change(agent):
    seen(agent)
    agent.client = ScriptedClient(
        lambda _: {
            "reflection": "A thought",
            "sources": [999],
            "insights": [{"change": "add", "belief": "Unwitnessed claim"}],
        }
    )
    with pytest.raises(StructuredOutputError):
        await agent.reflect(
            time_at(1, "13:00"), mode="experience", activity_id="chat", reflection_id="bad"
        )
    assert agent.memory.insights.read() == []
    assert not any(e["type"] in {"prepared", "completed"} for e in _entries(agent))


async def test_cancelled_experience_reuses_scope_without_late_or_future_events(agent):
    seen(agent, "FIRST")
    entered = asyncio.Event()

    class Interrupted:
        async def complete(self, request):
            entered.set()
            await asyncio.Event().wait()

    agent.client = Interrupted()
    pending = asyncio.create_task(
        agent.reflect(
            time_at(1, "13:00"), mode="experience", activity_id="chat", reflection_id="fixed"
        )
    )
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    seen(agent, "LATE", 2)
    seen(agent, "FUTURE", 3, time_at(2, "12:00"))
    requests = []
    agent.client = ScriptedClient(lambda r: requests.append(r) or {"reflection": "Original only"})
    await agent.reflect(
        time_at(1, "14:00"), mode="experience", activity_id="chat", reflection_id="fixed"
    )
    assert "FIRST" in requests[0].messages[-1].content
    assert "LATE" not in requests[0].messages[-1].content
    assert "FUTURE" not in requests[0].messages[-1].content
    assert len([e for e in _entries(agent) if e["type"] == "scope"]) == 1


async def test_experience_leave_saves_no_changes(agent):
    seen(agent)
    agent.client = ScriptedClient(lambda _: {"do": "leave"})
    result = await agent.reflect(
        time_at(1, "13:00"), mode="experience", activity_id="chat", reflection_id="left"
    )
    assert result["status"] == "left"
    assert agent.memory.skills.read() == [] and agent.memory.insights.read() == []
    assert not any(e["type"] == "prepared" for e in _entries(agent))


async def test_daily_is_written_once_and_keeps_night_reflection_visible(agent, script):
    seen(agent)
    agent.client = ScriptedClient(lambda _: {"reflection": "DAYTIME_REFLECTION", "sources": [1]})
    await agent.reflect(
        time_at(1, "13:00"), mode="experience", activity_id="chat", reflection_id="daytime"
    )
    agent.client = script.client
    await agent.reflect(time_at(1, "22:00"), mode="daily")
    await agent.reflect(time_at(1, "22:01"), mode="daily")
    assert len(script.prompts("diary")) == 1
    assert "DAYTIME_REFLECTION" in script.prompts("diary")[0]
    assert len(agent.memory.diary.entries()) == 1


async def test_conversation_summary_is_saved_with_no_work_notes(agent):
    seen(agent, "CHAT_RESULT")
    requests = []
    agent.client = ScriptedClient(
        lambda r: requests.append(r) or {"summary": "The conversation clarified a result."}
    )
    for _ in range(2):
        result = await agent.reflect(
            time_at(1, "13:00"), mode="summary", activity_id="chat", reflection_id="chat-summary"
        )
    assert result["summary"] == "The conversation clarified a result."
    assert len(requests) == 1 and "CHAT_RESULT" in requests[0].messages[-1].content


async def test_stable_seq_bounds_keep_heard_speech_across_retention_and_same_minute_visits(agent):
    from core.agent.memory import Record

    time = time_at(2, "12:00")
    seen(agent, "OLD_DAY", 0, time_at(1, "12:00"))
    seen(agent, "FIRST_VISIT", 1, time)
    seen(agent, "SECOND_VISIT_HEARD", 2, time)
    agent.memory.episodic.append(
        [
            Record(
                time=time,
                text="OTHER_VISIT_OWN_ACTION",
                activity_id="chat",
                activity_visit_id="old",
            ),
            Record(time=time, text="OWN_ACTION", activity_id="chat", activity_visit_id="mine"),
        ]
    )
    agent.memory.episodic.drop_before(time)
    requests = []
    agent.client = ScriptedClient(
        lambda request: requests.append(request) or {"reflection": "Heard and considered."}
    )
    await agent.reflect(
        time + 1,
        mode="experience",
        activity_id="chat",
        visit_id="mine",
        reflection_id="bounded",
        source_start=time,
        source_end=time,
        source_seq_start=2,
        source_seq_end=3,
    )
    prompt = requests[0].messages[-1].content
    assert "SECOND_VISIT_HEARD" in prompt and "OWN_ACTION" in prompt
    assert "FIRST_VISIT" not in prompt and "OTHER_VISIT_OWN_ACTION" not in prompt


async def test_experience_budget_keeps_skill_bodies_out_of_required_instruction(agent):
    import re

    from core.agent.config import ContextBudgetConfig
    from core.agent.context import Counter, input_limit
    from core.agent.memory import Skill

    agent.cognition = agent.cognition.model_copy(
        update={
            "context_budget": ContextBudgetConfig(enabled=True, input_tokens=10000),
        }
    )
    for index in range(8):
        agent.memory.skills.write(
            Skill(
                name=f"method-{index}",
                title=f"Method {index}",
                description="A method to consider",
                body="UNNEEDED_FULL_BODY " * 600,
            )
        )
    seen(agent, "Result")

    def reply(request):
        assert Counter(agent.cognition.context_budget).request(request) <= input_limit(
            agent.cognition.context_budget, request
        )
        assert "UNNEEDED_FULL_BODY" not in request.messages[-1].content
        bound = request.json_schema["$defs"]["Experience"]["properties"]["reflection"]["maxLength"]
        prompt_bound = re.search(
            r"reflection/summary limit: (\d+) characters", request.messages[-1].content
        )
        assert prompt_bound and int(prompt_bound.group(1)) == bound
        assert bound < 500  # The rich schema forces the initial output bound to shrink.
        return {"reflection": "I can keep my methods for now."}

    agent.client = ScriptedClient(reply)
    await agent.reflect(
        time_at(1, "13:00"), mode="experience", activity_id="chat", reflection_id="budget"
    )
