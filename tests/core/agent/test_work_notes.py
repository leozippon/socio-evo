"""Work journals retain witnessed evidence without leaking across residents or time."""

import json

import pytest

from core.agent.config import ActiveRecallConfig, ContextBudgetConfig, WorkNotesConfig
from core.agent.memory.active import search
from core.agent.memory.work import WorkNotes
from core.interaction import Event, EventKind, MayRunCommand, time_at


def event(seq=1, **updates):
    fields = dict(
        seq=seq,
        time=time_at(1, "10:00"),
        kind=EventKind.WORK_CHECKED,
        audience=("Mei",),
        text="Parser timezone test failed.",
        payload={"task_id": "task-1", "hidden_tests": "SECRET"},
    )
    return Event(**(fields | updates))


def test_public_task_routing_never_copies_hidden_payload():
    seen = event().percept("Mei")
    assert seen.task_id == "task-1"
    assert "SECRET" not in seen.model_dump_json()
    assert event().percept("Tomas").task_id is None
    assert event(kind=EventKind.WORK_ASSESSED).percept("Mei").task_id is None
    assert event(kind=EventKind.ACTION_REJECTED).percept("Mei").task_id == "task-1"
    assert event(payload={"task_id": "../../Tomas"}).percept("Mei").task_id is None


def test_journal_deduplicates_and_survives_reopening(agent):
    notes = agent.memory.work
    notes.observe(event().percept("Mei"))
    notes.observe(event().percept("Mei"))
    notes.record("task-1", time_at(1, "11:00"), "intention", "I will fix the parser.")
    reopened = WorkNotes(notes.root)
    assert len(reopened.entries("task-1")) == 2
    state = json.loads((notes.root / "task-1/state.json").read_text())
    assert state["last_observation"]["text"] == "Parser timezone test failed."
    assert state["last_intention"]["text"] == "I will fix the parser."
    assert len(reopened.entries("task-1", time_at(1, "10:30"))) == 1
    assert "SECRET" not in (notes.root / "task-1/events.jsonl").read_text()


def test_notes_are_owned_and_symlink_escape_is_rejected(agent, tmp_path):
    notes = agent.memory.work
    other = WorkNotes(tmp_path / "Tomas/memory/work")
    other.record("task-9", 1, "observation", "private-secret telescope")
    notes.root.mkdir(parents=True)
    (notes.root / "task-9").symlink_to(other.root / "task-9", target_is_directory=True)
    assert notes.tasks() == []
    with pytest.raises(ValueError):
        notes.entries("task-9")
    with pytest.raises(ValueError):
        notes.record("../Tomas", 1, "intention", "bad path")
    assert search(agent.memory, "private-secret telescope", 10, ActiveRecallConfig()) == []


def test_context_selects_current_or_related_but_not_all_notes(agent, observe):
    notes = agent.memory.work
    notes.observe(event().percept("Mei"))
    notes.record("task-2", time_at(1, "11:00"), "observation", "Telescope optics repaired.")
    notes.save_summary("task-1", time_at(1, "11:00"), "Parser timezone failed.", (0, 0), (1, 28))
    cfg = WorkNotesConfig(enabled=True)
    work = observe(2).model_copy(
        update={
            "allowed": (MayRunCommand(task_id="task-1", parts=(1,)),),
            "situation": "You are working.",
            "percepts": (),
        }
    )
    blocks = notes.select(work, cfg, agent.setting)
    assert [b.source for b in blocks] == ["work-note:task-1"]
    assert blocks[0].priority == 95
    unrelated = observe(2).model_copy(update={"situation": "A sunny morning.", "percepts": ()})
    assert notes.select(unrelated, cfg, agent.setting) == []
    related = unrelated.model_copy(update={"situation": "Ben asks about parser timezone."})
    assert [b.source for b in notes.select(related, cfg, agent.setting)] == ["work-note:task-1"]
    explicit = unrelated.model_copy(update={"situation": "Discuss job 2."})
    assert [b.source for b in notes.select(explicit, cfg, agent.setting)] == ["work-note:task-2"]


def test_recall_has_timestamp_provenance_and_excludes_future(agent):
    notes = agent.memory.work
    notes.observe(event().percept("Mei"))
    notes.record("task-1", time_at(3, "11:00"), "observation", "Future timezone secret.")
    notes.save_summary("task-1", time_at(1, "11:00"), "Timezone failure summary.", (0, 0), (1, 28))
    hits = search(
        agent.memory, "timezone", time_at(2, "12:00"), ActiveRecallConfig(), summarized_work=True
    )
    assert hits and "events.jsonl:id=summary:3" in hits[0].source
    assert "11:00" in hits[0].render(agent.setting)
    assert all("Future" not in hit.text for hit in hits)


@pytest.mark.parametrize("budget", [False, True])
async def test_notes_injected_into_decision_and_nightly_context(agent, observe, script, budget):
    agent.cognition = agent.cognition.model_copy(
        update={
            "work_notes": WorkNotesConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=budget),
        }
    )
    agent.perceive([event().percept("Mei")])
    observation = observe(1).model_copy(
        update={
            "time": time_at(1, "12:00"),
            "situation": "Ben asks about job 1.",
            "own_task_id": "task-1",
            "work_activity": True,
        }
    )
    await agent.act(observation)
    request = script.requests[-1]
    assert request.metadata["work_notes"] == ["work-log:task-1:1"]
    assert "Parser timezone test failed" in request.messages[-1].content
    assert "source: percept:1" in request.messages[-1].content
    await agent.write("diary", time_at(1, "22:00"), "Write about today.")
    assert "Your work notes for job 1" in script.requests[-1].messages[-1].content
    if budget:
        assert all(r.metadata["context_usage"]["input_count"] <= 24000 for r in script.requests)


def test_disabled_does_not_create_notes(agent):
    agent.perceive([event().percept("Mei")])
    assert not agent.memory.work.root.exists()


@pytest.mark.parametrize("budget", [False, True])
async def test_previous_job_reads_keep_current_logs_and_prior_pages(agent, observe, budget):
    from infrastructure.llm import ScriptedClient

    agent.cognition = agent.cognition.model_copy(
        update={
            "work_notes": WorkNotesConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=budget),
        }
    )
    notes = agent.memory.work
    notes.record("task-1", 1, "observation", "CURRENT_EARLY")
    notes.record("task-1", 2, "observation", "CURRENT_LATEST")
    notes.write_note("task-1", 3, "CURRENT_SUMMARY_MUST_NOT_APPEAR")
    notes.record("task-2", 1, "observation", "OLD_PAGE_START " + "x" * 6200 + " OLD_PAGE_END")
    requests = []

    def reply(request):
        requests.append(request)
        prompt = "\n".join(m.content for m in request.messages)
        assert "CURRENT_EARLY" in prompt and "CURRENT_LATEST" in prompt
        assert "CURRENT_SUMMARY_MUST_NOT_APPEAR" not in prompt
        options = request.json_schema["$defs"]["ReadPreviousWorkLog"]["properties"]["job"]
        assert options.get("const") == "job 2"
        if len(requests) <= 2:
            if len(requests) == 2:
                assert "OLD_PAGE_START" in prompt
            return {
                "thought": "Read the previous job.",
                "do": "read work record",
                "job": "job 2",
                "start": 1,
                "offset": 0 if len(requests) == 1 else 5900,
            }
        assert "OLD_PAGE_START" in prompt and "OLD_PAGE_END" in prompt
        return {"thought": "Discuss", "do": "say", "to": "Ben", "words": "I read the record."}

    agent.client = ScriptedClient(reply)
    await agent.act(observe(2).model_copy(update={"own_task_id": "task-1", "work_activity": True}))
    assert len(requests) == 3
    assert all(r.metadata["purpose"] == "act" for r in requests)


@pytest.mark.parametrize("budget", [False, True])
async def test_current_job_all_raw_visits_survive_skill_selection_and_recall(
    agent, observe, budget
):
    from core.agent.memory import Skill
    from infrastructure.llm import ScriptedClient

    agent.cognition = agent.cognition.model_copy(
        update={
            "work_notes": WorkNotesConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=budget),
            "active_recall": ActiveRecallConfig(enabled=True),
        }
    )
    notes = agent.memory.work
    logs = [f"RAW_OPERATION_{i}: command and full feedback " + "x" * 1750 for i in range(7)]
    for i, text in enumerate(logs):
        notes.record(
            "task-1", i + 1, "observation", text, activity_id="work-1", visit_id=str(i % 2)
        )
    notes.write_note("task-1", 9, "FORBIDDEN_CURRENT_SUMMARY parser timezone")
    notes.record("task-1", time_at(3, "10:00"), "observation", "FUTURE_FEEDBACK")
    agent.memory.skills.write(
        Skill(
            name="check-first",
            title="Check first",
            description="For repairs.",
            body="SELECTED_METHOD: test the caller.",
        )
    )
    requests = []
    answers = iter(
        [
            {"thought": "Recall", "do": "recall something", "query": "parser timezone"},
            {"thought": "Use method", "do": "use skill", "name": "check-first"},
            {"thought": "x" * 801, "do": "use the terminal", "command": "python -m pytest"},
            {"thought": "Run test", "do": "use the terminal", "command": "python -m pytest"},
            {"thought": "Continue", "do": "use the terminal", "command": "git diff"},
        ]
    )

    def reply(request):
        requests.append(request)
        prompt = "\n".join(m.content for m in request.messages)
        for text in logs:
            assert text in prompt
        assert "FORBIDDEN_CURRENT_SUMMARY" not in prompt
        assert "FUTURE_FEEDBACK" not in prompt
        assert "ReadPreviousWorkLog" not in str(request.json_schema)
        assert "TASK_REQUIREMENT" in prompt and "LIVE_SOCIAL_MESSAGE" in prompt
        if len(requests) >= 3:
            assert "SELECTED_METHOD" in prompt
        return next(answers)

    agent.client = ScriptedClient(reply)
    observation = observe(2, "LIVE_SOCIAL_MESSAGE").model_copy(
        update={
            "activity_kind": "work",
            "activity_id": "work-1",
            "activity_visit_id": "second",
            "activity_task_id": "task-1",
            "own_task_id": "task-1",
            "work_activity": True,
            "situation": "TASK_REQUIREMENT",
            "allowed": (MayRunCommand(task_id="task-1", parts=(1,)),),
        }
    )
    await agent.act(observation)
    await agent.act(observation.model_copy(update={"time": observation.time + 1}))
    assert len(requests) == 5
    assert requests[3].after_invalid


async def test_large_current_job_keeps_latest_feedback_and_marks_omitted_prefix(agent, observe):
    from infrastructure.llm import ScriptedClient

    agent.cognition = agent.cognition.model_copy(
        update={
            "work_notes": WorkNotesConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=True, input_tokens=6000),
        }
    )
    notes = agent.memory.work
    notes.record("task-1", 1, "observation", "OLDEST " + "a" * 15000)
    notes.record("task-1", 2, "observation", "MIDDLE " + "b" * 5000)
    notes.record("task-1", 3, "observation", "RECENT_BEFORE_LAST")
    notes.observe(event(seq=20, time=4, text="LATEST_FULL_FEEDBACK " + "c" * 1200).percept("Mei"))
    notes.record("task-1", 5, "observation", "LATER_DESK_NOTICE")
    requests = []

    def reply(request):
        requests.append(request)
        prompt = "\n".join(m.content for m in request.messages)
        assert "Earlier original log omitted" in prompt
        assert "OLDEST" not in prompt
        assert "RECENT_BEFORE_LAST" in prompt
        assert "LATEST_FULL_FEEDBACK " + "c" * 1200 in prompt
        assert "LATER_DESK_NOTICE" in prompt
        assert request.metadata["context_usage"]["input_count"] <= 6000
        return {"thought": "Test", "do": "use the terminal", "command": "python -m pytest"}

    agent.client = ScriptedClient(reply)
    await agent.act(
        observe(2).model_copy(
            update={
                "own_task_id": "task-1",
                "work_activity": True,
                "allowed": (MayRunCommand(task_id="task-1", parts=(1,)),),
            }
        )
    )
    assert len(requests) == 1
    assert len(notes.entries("task-1")) == 5


async def test_current_job_cannot_be_read_as_previous_job(agent, observe):
    from infrastructure.llm import ScriptedClient

    agent.cognition = agent.cognition.model_copy(
        update={"work_notes": WorkNotesConfig(enabled=True)}
    )
    for task in ("task-1", "task-2"):
        agent.memory.work.record(task, 1, "observation", f"Observed {task}")
    replies = iter(
        [
            {"thought": "Read", "do": "read work record", "job": "job 1", "start": 1, "offset": 0},
            {"thought": "Act", "do": "say", "to": "Ben", "words": "Proceed."},
        ]
    )
    requests = []

    def reply(request):
        requests.append(request)
        return next(replies)

    agent.client = ScriptedClient(reply)
    await agent.act(observe(2).model_copy(update={"own_task_id": "task-1", "work_activity": True}))
    assert len(requests) == 2 and requests[-1].after_invalid
    assert requests[-1].metadata["work_record_reads"] == []


def test_summary_as_of_time_and_symlink_protection(agent, tmp_path):
    notes = agent.memory.work
    notes.observe(event().percept("Mei"))
    notes.write_note("task-1", time_at(2, "11:00"), "OLD_SUMMARY")
    notes.write_note("task-1", time_at(3, "11:00"), "FUTURE_SUMMARY")
    view = notes.render("task-1", time_at(2, "12:00"), WorkNotesConfig(), agent.setting)
    assert "OLD_SUMMARY" in view and "FUTURE_SUMMARY" not in view
    target = tmp_path / "other-agent-note"
    target.write_text("PRIVATE")
    (notes.root / "task-1/note.md").unlink()
    (notes.root / "task-1/note.md").symlink_to(target)
    with pytest.raises(ValueError):
        notes.write_note("task-1", time_at(4, "12:00"), "rewrite")
    assert target.read_text() == "PRIVATE"


async def test_oversized_latest_feedback_is_never_silently_dropped(agent, observe, script):
    from core.agent.context import ContextOverflow

    agent.cognition = agent.cognition.model_copy(
        update={
            "work_notes": WorkNotesConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=True, input_tokens=6000),
        }
    )
    agent.memory.work.record("task-1", 1, "observation", "LATEST " + "x" * 10000)
    with pytest.raises(ContextOverflow, match="latest feedback"):
        await agent.act(
            observe(2).model_copy(update={"own_task_id": "task-1", "work_activity": True})
        )
    assert not script.requests
