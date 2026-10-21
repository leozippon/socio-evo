"""Operational records stay recoverable without entering every conversational prompt."""

import asyncio

import pytest

from core.agent.config import ContextBudgetConfig, WorkNotesConfig
from core.agent.continuation import DecisionContinuation
from core.agent.memory.work import WorkNotes
from core.interaction import EventKind, MayActivity, Percept
from infrastructure.llm import (
    ScriptedClient,
    StructuredOutputError,
)


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


@pytest.mark.parametrize("length,mode", [(10000, "full"), (26000, "excerpted")])
async def test_one_activity_overview_uses_whole_input_or_honest_excerpts(agent, length, mode):
    from core.agent.context import Counter, input_limit

    enable(agent, True)
    notes = agent.memory.work
    raw = "BEGIN " + "x" * length + " END"
    notes.begin_activity("visit", "task-1", 1)
    notes.record("task-1", 1, "observation", raw, activity_id="visit")
    requests = []

    def answer(request):
        requests.append(request)
        assert request.structured_output == "json_schema"
        assert 1 <= request.json_schema["properties"]["summary"]["maxLength"] <= 1600
        assert Counter(agent.cognition.context_budget).request(request) <= input_limit(
            agent.cognition.context_budget, request
        )
        assert request.metadata["work_input_mode"] == mode
        prompt = request.messages[-1].content
        assert "BEGIN" in prompt and " END" in prompt
        if mode == "full":
            assert raw in prompt
        else:
            assert "omitted text has NOT been read" in prompt and raw not in prompt
        notes.record("task-1", 2, "observation", "ARRIVED_DURING_SUMMARY", activity_id="later")
        return {"summary": "Bounded working overview."}

    agent.client = ScriptedClient(answer)
    await agent.summarize_work(20, activity_id="visit")
    await agent.summarize_work(21, activity_id="visit")
    assert len(requests) == 1
    overview = notes.summaries("task-1")[0]
    assert overview["input_mode"] == mode and overview["source_entries"] == [2]
    assert notes.cursor("task-1") == (0, 0)  # A range overview is not a full-character receipt.
    reopened = WorkNotes(notes.root)
    assert reopened.pending_scopes("visit") == []
    assert "BEGIN" in reopened.read_range("task-1", 2, 0)
    assert " END" in reopened.read_range("task-1", 2, length - 100)


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
    agent.perceive([receipt("READY_RESULT").model_copy(update={"activity_id": "visit"})])
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
            "activity_id": "visit",
            "activity_kind": "work",
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
    assert agent.memory.work.pending_scopes("visit") == []
    assert len(agent.memory.work.summaries("task-1")) == 1


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


async def test_nightly_history_is_one_bounded_batch_under_small_budget(agent):
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
    assert len(notes.summaries("task-1")) == 1
    assert notes.cursor("task-1") == before
    assert len(requests) == 1
    assert requests[0].metadata["work_input_mode"] == "excerpted"


async def test_nightly_work_catchup_runs_with_evolution_disabled(agent):
    from types import SimpleNamespace

    from core.agent.evolution import EvolutionConfig, Evolver
    from runtime.simulation.simulation import Simulation

    enable(agent)
    agent.memory.work.record("task-1", 1, "observation", "FINISHED_JOB_RESULT")
    agent.client = ScriptedClient(lambda _: {"summary": "Finished job result retained."})
    owner = SimpleNamespace(evolver=Evolver(EvolutionConfig(levels=())))
    assert await Simulation._evolve(owner, agent, (), 20) == []
    overview = agent.memory.work.summaries("task-1")[0]
    assert overview["legacy"] and overview["input_mode"] == "full"
    assert agent.memory.work.cursor("task-1") == (0, 0)
    assert not agent.memory.work.pending_scopes()


async def test_exits_never_merge_and_night_compacts_once(agent):
    enable(agent)
    notes = agent.memory.work
    requests = []
    agent.client = ScriptedClient(
        lambda r: requests.append(r) or {"summary": "Observed result retained."}
    )
    for index in range(6):
        activity = f"visit-{index}"
        notes.begin_activity(activity, "task-1", index)
        notes.record("task-1", index, "observation", f"Operation {index}", activity_id=activity)
        await agent.summarize_work(100 + index, activity_id=activity)
    assert len(requests) == 6
    assert all(r.metadata["purpose"] == "work_summary" for r in requests)
    assert len(notes.summaries("task-1")) == 6
    await agent.summarize_work(200)
    assert len(requests) == 7 and requests[-1].metadata["purpose"] == "work_summary_merge"
    assert len(notes.summaries("task-1")) == 1
    history = notes.summaries("task-1")[0]
    assert history["period"] == [0, 5]
    assert len(history["replaces"]) == 6
    assert [e["period"] for e in notes.entries("task-1") if e["id"] in history["replaces"]] == [
        [i, i] for i in range(6)
    ]
    await agent.summarize_work(201)
    assert len(requests) == 7


async def test_activity_scope_follows_real_jobs_excludes_old_backlog_and_empty_visits(agent):
    enable(agent)
    notes = agent.memory.work
    notes.record("task-1", 1, "observation", "LEGACY_BACKLOG")
    notes.observe(receipt("OLD_DELAYED").model_copy(update={"activity_id": "old"}))
    notes.begin_activity("visit", "task-3", 2)
    notes.observe(
        receipt("CLAIM_ONLY", 2, "task-3").model_copy(
            update={"activity_id": "visit", "kind": EventKind.DESK}
        )
    )
    for seq, task in [(3, "task-1"), (4, "task-2")]:
        notes.begin_activity("visit", task, 2)
        notes.observe(
            receipt("ACTUAL_RESULT", seq, task).model_copy(update={"activity_id": "visit"})
        )
    requests = []
    agent.client = ScriptedClient(
        lambda r: requests.append(r) or {"summary": "Current visit result."}
    )
    await agent.summarize_work(20, {"task-2"}, activity_id="visit")
    assert len(requests) == 2  # A completed former job is not filtered by current ownership.
    assert all(
        "LEGACY_BACKLOG" not in r.messages[-1].content
        and "OLD_DELAYED" not in r.messages[-1].content
        for r in requests
    )
    assert notes.summaries("task-3") == []
    await agent.summarize_work(21, activity_id="empty")
    assert len(requests) == 2


async def test_small_budget_retry_keeps_dynamic_limit_and_operation_index(agent):
    from core.agent.context import Counter, input_limit

    enable(agent, True)
    budget = agent.cognition.context_budget.model_copy(update={"input_tokens": 4000})
    agent.cognition = agent.cognition.model_copy(update={"context_budget": budget})
    notes = agent.memory.work
    notes.begin_activity("visit", "task-1", 1)
    for index in range(4):
        notes.record("task-1", index, "observation", "证据" * 4000, activity_id="visit")
    requests = []

    def reply(request):
        requests.append(request)
        assert Counter(budget).request(request) <= input_limit(budget, request)
        bound = request.json_schema["properties"]["summary"]["maxLength"]
        assert bound < 1600
        if len(requests) == 1:
            return {"summary": "证" * (bound + 1)}
        assert request.after_invalid
        return {"summary": "Observed results retained; details remain in the original entries."}

    agent.client = ScriptedClient(reply)
    await agent.summarize_work(20, activity_id="visit")
    assert len(requests) == 2 and not notes.pending_scopes("visit")


async def test_cancelled_scope_does_not_absorb_late_receipts_or_conversation(agent):
    enable(agent)
    notes = agent.memory.work
    notes.begin_activity("visit", "task-1", 1)
    notes.record("task-1", 1, "observation", "FIRST", activity_id="visit")
    entered = asyncio.Event()

    class CancelledClient:
        async def complete(self, request):
            entered.set()
            await asyncio.Event().wait()

    agent.client = CancelledClient()
    task = asyncio.create_task(agent.summarize_work(10, activity_id="visit"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pending = notes.pending_scopes("visit")[0][1]
    assert pending["source_entries"] == [2]
    notes.record("task-1", 11, "observation", "LATE", activity_id="visit")
    notes.observe(
        receipt("CONVERSATION", 44).model_copy(
            update={"activity_id": "chat", "kind": EventKind.ACTIVITY_FEEDBACK}
        )
    )
    requests = []
    agent.client = ScriptedClient(lambda r: requests.append(r) or {"summary": "Visit overview."})
    await agent.summarize_work(12, activity_id="visit")
    assert len(requests) == 1 and "LATE" not in requests[0].messages[-1].content
    await agent.summarize_work(13, activity_id="visit")
    assert len(requests) == 1
    await agent.summarize_work(20)
    assert len(requests) == 2 and "LATE" in requests[-1].messages[-1].content
    assert all("CONVERSATION" not in r.messages[-1].content for r in requests)


async def test_one_night_finishes_cancelled_snapshot_and_late_receipt(agent):
    enable(agent)
    notes = agent.memory.work
    notes.begin_activity("visit", "task-1", 1)
    notes.record("task-1", 2, "observation", "EARLIER", activity_id="visit")
    entered = asyncio.Event()

    class Interrupted:
        async def complete(self, request):
            entered.set()
            await asyncio.Event().wait()

    agent.client = Interrupted()
    running = asyncio.create_task(agent.summarize_work(10, activity_id="visit"))
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    original = notes.pending_scopes("visit")[0][1]
    notes.record("task-1", 11, "observation", "LATER", activity_id="visit")
    requests = []
    agent.client = ScriptedClient(lambda r: requests.append(r) or {"summary": "Observed work."})
    await agent.summarize_work(20)
    assert len(requests) == 2
    assert "EARLIER" in requests[0].messages[-1].content
    assert "LATER" not in requests[0].messages[-1].content
    assert "LATER" in requests[1].messages[-1].content
    assert original["source_entries"] == [2] and not notes.pending_scopes()
    await agent.summarize_work(21)
    assert len(requests) == 2
