"""Operational records stay recoverable without entering every conversational prompt."""

import asyncio

import pytest

from core.agent.config import ContextBudgetConfig, WorkNotesConfig
from core.agent.continuation import DecisionContinuation
from core.agent.memory.work import WorkNotes
from core.interaction import EventKind, MayActivity, Percept
from infrastructure.llm import ScriptedClient, StructuredOutputError


def enable(agent, budget=False):
    agent.cognition = agent.cognition.model_copy(
        update={
            "work_notes": WorkNotesConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=budget),
        }
    )


def receipt(text, seq=1, task="task-1"):
    return Percept(seq=seq, time=10, kind=EventKind.COMMAND_EXECUTED, task_id=task, text=text)


@pytest.mark.parametrize("budget", [False, True])
async def test_current_work_feedback_persists_once_and_history_stays_private(
    agent, observe, script, budget
):
    enable(agent, budget)
    agent.perceive([receipt("CURRENT_RAW"), receipt("OLD_JOB_RAW", 2, "task-2")])
    agent.memory.work.save_summary("task-2", 11, "Old job concise result", (0, 0), (1, 11))
    observation = observe(1).model_copy(
        update={
            "own_task_id": "task-1",
            "work_activity": True,
            "work_feedback": ("CURRENT_RAW",),
            "situation": "Here.\nCURRENT_RAW",
            "evidence": ("CURRENT_RAW",),
            "operational_evidence": True,
        }
    )
    await agent.act(observation)
    await agent.act(observation.model_copy(update={"percepts": ()}))
    prompt = script.requests[-1].messages[-1].content
    assert prompt.count("CURRENT_RAW") == 1
    assert "OLD_JOB_RAW" not in prompt
    nonwork = observation.model_copy(
        update={
            "work_activity": False,
            "work_feedback": (),
            "situation": "Discuss job 2",
            "percepts": (),
            "evidence": ("Independent evidence",),
            "operational_evidence": False,
        }
    )
    await agent.act(nonwork)
    prompt = script.requests[-1].messages[-1].content
    assert "CURRENT_RAW" not in prompt and "OLD_JOB_RAW" not in prompt
    assert "Independent evidence" in prompt
    assert "Old job concise result" in prompt


async def test_job_tagged_chat_remains_verbatim_and_is_not_summarized(agent, observe, script):
    enable(agent)
    chat = receipt("CHAT_TERMINAL_WORDS", task="task-1").model_copy(
        update={"kind": EventKind.SPEECH}
    )
    await agent.act(observe(1).model_copy(update={"percepts": (chat,)}))
    assert "CHAT_TERMINAL_WORDS" in script.requests[-1].messages[-1].content
    assert agent.memory.work.tasks() == []
    assert agent.memory.episodic.read()[0].text == "CHAT_TERMINAL_WORDS"


async def test_summary_pages_long_entries_merges_and_preserves_snapshot_boundary(agent):
    enable(agent, True)
    notes = agent.memory.work
    raw = "BEGIN " + "x" * 26000 + " END"
    notes.record("task-1", 1, "observation", raw)
    requests = []

    def answer(request):
        requests.append(request)
        assert all(message.role != "assistant" for message in request.messages)
        assert len(request.messages[-1].content) < 8000
        if len(requests) == 1:
            notes.record("task-1", 1, "observation", "ARRIVED_DURING_SUMMARY")
        return {"summary": "Bounded working summary."}

    agent.client = ScriptedClient(answer)
    await agent.summarize_work(20)
    assert notes.cursor("task-1") == (1, len(raw))
    assert len(notes.summaries("task-1")) < 4
    assert any(r.metadata["purpose"] == "work_summary_merge" for r in requests)
    assert not any("ARRIVED_DURING_SUMMARY" in r.messages[-1].content for r in requests)
    reopened = WorkNotes(notes.root)
    assert reopened.cursor("task-1") == notes.cursor("task-1")
    await agent.summarize_work(21)
    assert reopened.cursor("task-1") == (2, len("ARRIVED_DURING_SUMMARY"))
    assert "BEGIN" in reopened.read_range("task-1", 1, 0)
    assert " END" in reopened.read_range("task-1", 1, 25000)
    assert len(reopened.render("task-1", 30, agent.cognition.work_notes, agent.setting)) < 7000


async def test_failed_summary_never_moves_coverage(agent):
    enable(agent)
    agent.memory.work.record("task-1", 1, "observation", "UNSUMMARIZED")
    agent.client = ScriptedClient(lambda request: {"summary": ""})
    with pytest.raises(StructuredOutputError):
        await agent.summarize_work(20)
    assert agent.memory.work.cursor("task-1") == (0, 0)
    assert agent.memory.work.entries("task-1")[0]["text"] == "UNSUMMARIZED"


async def test_rest_exit_waits_for_summary_and_cancel_does_not_commit_old_choice(agent, observe):
    enable(agent)
    agent.perceive([receipt("READY_RESULT")])
    started, release = asyncio.Event(), asyncio.Event()

    class Client:
        async def complete(self, request):
            if request.metadata["purpose"] == "work_summary":
                started.set()
                await release.wait()
                return await ScriptedClient(lambda _: {"summary": "Result saved."}).complete(
                    request
                )
            return await ScriptedClient(
                lambda _: {
                    "thought": "Rest now",
                    "do": "rest",
                    "day": "today",
                    "until": "12:00",
                    "wake for invitations": True,
                }
            ).complete(request)

    agent.client = Client()
    observation = observe(1).model_copy(
        update={
            "own_task_id": "task-1",
            "work_activity": True,
            "allowed": (
                MayActivity(
                    layer="tool",
                    menu={
                        "tools": ["leave"],
                        "costs": {},
                        "places": {},
                        "people": [],
                        "invitations": [],
                    },
                ),
            ),
        }
    )
    continuation = DecisionContinuation()
    pending = asyncio.create_task(agent.choose_tool(observation, continuation=continuation))
    await started.wait()
    assert continuation.summarizing_work and not pending.done()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not continuation.summarizing_work and not continuation.committed
    assert agent.memory.work.cursor("task-1") == (0, 0)
    release.set()
    await agent.choose_tool(observation, continuation=continuation)
    continuation.commit()
    assert agent.memory.work.cursor("task-1") == (1, len("READY_RESULT"))


@pytest.mark.parametrize("budget", [False, True])
async def test_summary_recalled_once_and_disabled_recall_keeps_original_behavior(
    agent, observe, budget
):
    from core.agent.config import ActiveRecallConfig
    from core.agent.memory import Record
    from core.agent.memory.active import search

    agent.memory.episodic.append([Record.of(receipt("RAW_DISABLED_QUERY"))])
    assert search(agent.memory, "RAW_DISABLED_QUERY", 100, ActiveRecallConfig())
    assert not search(
        agent.memory, "RAW_DISABLED_QUERY", 100, ActiveRecallConfig(), summarized_work=True
    )
    enable(agent, budget)
    agent.cognition = agent.cognition.model_copy(
        update={"active_recall": ActiveRecallConfig(enabled=True)}
    )
    notes = agent.memory.work
    notes.record("task-1", 1, "observation", "Raw terminal output")
    notes.save_summary("task-1", 2, "UNIQUE_SUMMARY_MARKER parser timezone", (0, 0), (1, 19))
    requests = []

    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return {
                "thought": "Remember the result",
                "do": "recall something",
                "query": "parser timezone",
            }
        return {"thought": "Discuss", "do": "say", "to": "Ben", "words": "I remember."}

    agent.client = ScriptedClient(reply)
    await agent.act(observe(1).model_copy(update={"own_task_id": "task-1"}))
    assert len(requests) == 2
    assert requests[-1].messages[-1].content.count("UNIQUE_SUMMARY_MARKER") == 1


async def test_small_budget_merges_multibyte_summaries_without_stalling(agent):
    from core.agent.context import Counter, input_limit

    enable(agent, True)
    budget = agent.cognition.context_budget.model_copy(update={"input_tokens": 4000})
    agent.cognition = agent.cognition.model_copy(update={"context_budget": budget})
    notes = agent.memory.work
    for index in range(4):
        notes.record("task-1", index, "observation", f"result {index}")
        entry = len(notes.entries("task-1"))
        notes.save_summary(
            "task-1", index, f"Summary {index}: " + "证据" * 790, (entry, 0), (entry, 8)
        )
    before = notes.cursor("task-1")
    requests = []

    def respond(request):
        requests.append(request)
        assert Counter(budget).request(request) <= input_limit(budget, request)
        return {"summary": "Earlier results and unresolved work preserved."}

    agent.client = ScriptedClient(respond)
    await agent.summarize_work(30)
    assert len(notes.summaries("task-1")) == 3
    assert notes.cursor("task-1") == before
    assert len(requests) > 1
    # Only the two oldest records were replaced; later summaries remain intact.
    remaining = " ".join(entry["text"] for entry in notes.summaries("task-1"))
    assert "Summary 2:" in remaining and "Summary 3:" in remaining


async def test_nightly_work_catchup_runs_with_evolution_disabled(agent):
    from types import SimpleNamespace

    from core.agent.evolution import EvolutionConfig, Evolver
    from runtime.simulation.simulation import Simulation

    enable(agent)
    agent.memory.work.record("task-1", 1, "observation", "FINISHED_JOB_RESULT")
    agent.client = ScriptedClient(lambda _: {"summary": "Finished job result retained."})
    owner = SimpleNamespace(evolver=Evolver(EvolutionConfig(levels=())))
    assert await Simulation._evolve(owner, agent, (), 20) == []
    assert agent.memory.work.cursor("task-1") == (1, len("FINISHED_JOB_RESULT"))


async def test_repeated_merges_keep_summary_ranges_contiguous_and_ordered(agent):
    enable(agent)
    notes = agent.memory.work
    agent.client = ScriptedClient(lambda _: {"summary": "Earlier operations preserved."})
    for index in range(12):
        notes.record("task-1", index, "observation", f"Operation {index}")
        await agent.summarize_work(100 + index)
        summaries = notes.summaries("task-1")
        assert len(summaries) < 4
        ranges = [(tuple(e["from"]), tuple(e["through"])) for e in summaries]
        assert ranges == sorted(ranges)
        assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:], strict=False))
    assert notes.cursor("task-1") == ranges[-1][1]
