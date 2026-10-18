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
    hits = search(agent.memory, "timezone", time_at(2, "12:00"), ActiveRecallConfig())
    assert hits and "events.jsonl:id=event:1" in hits[0].source
    assert "10:00" in hits[0].render(agent.setting)
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
        update={"time": time_at(1, "12:00"), "situation": "Ben asks about job 1."}
    )
    await agent.act(observation)
    request = script.requests[-1]
    assert request.metadata["work_notes"] == ["work-note:task-1"]
    assert "Parser timezone test failed" in request.messages[-1].content
    assert "source: percept:1" in request.messages[-1].content
    await agent.write("diary", time_at(1, "22:00"), "Write about today.")
    assert "Your work notes for job 1" in script.requests[-1].messages[-1].content
    if budget:
        assert all(r.metadata["context_usage"]["input_count"] <= 24000 for r in script.requests)


def test_disabled_does_not_create_notes(agent):
    agent.perceive([event().percept("Mei")])
    assert not agent.memory.work.root.exists()
