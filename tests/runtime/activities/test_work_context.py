"""Assigned Work keeps task facts and operating rules ahead of budgeted original logs."""

import pytest

from core.agent import Agent, CognitionConfig
from core.agent.config import ContextBudgetConfig, WorkNotesConfig
from core.agent.memory import Record, Skill
from core.environment import Assessment
from core.interaction import EventKind, Percept, SubmitWork
from infrastructure.llm import ScriptedClient
from runtime.activities.model import at
from tests.core.agent.conftest import SEED, TOWN
from tests.runtime.activities import test_engine as base
from tests.runtime.activities import test_rest_transitions as transitions

engine = base.engine
scheduler = transitions.scheduler
RULES = "Working directory: /testbed. Use python tests/runtests.py --settings=test_sqlite <label>."


async def assigned(gate, monkeypatch):
    gate.now = at(1, "08:00")
    active = base.work(gate)
    await base.perform(gate, "Mei", "claim", job="task-1", partner=None)
    provider = next(iter(gate.env.providers.values()))
    monkeypatch.setattr(provider, "work_context", lambda part: RULES, raising=False)
    return active


async def test_focus_applies_only_to_assigned_work(scheduler, monkeypatch):
    scheduler.now = at(1, "08:00")
    active = base.work(scheduler)
    unassigned = scheduler.observation("Mei")
    assert unassigned.setting == scheduler.town_setting()
    assert "People here:" in unassigned.situation
    assert "Repository operating notes" not in unassigned.situation
    await base.perform(scheduler, "Mei", "claim", job="task-1", partner=None)
    provider = next(iter(scheduler.env.providers.values()))
    monkeypatch.setattr(provider, "work_context", lambda part: RULES, raising=False)
    chat = base.conversation(scheduler, people=("Tomas", "Aisha"), public=True)
    chat.topic = "UNRELATED_CHAT"
    task = scheduler.env.board.claim_of("Mei").task
    observation = scheduler.observation("Mei")
    assert observation.activity_task_id == task.id
    assert observation.situation.count(task.parts[0].specification) == 1
    assert RULES in observation.situation
    assert "Current location permits code work now: True" in observation.situation
    assert "People here:" not in observation.situation
    assert "UNRELATED_CHAT" not in observation.situation
    assert "Available public/paused work:" not in observation.situation
    assert scheduler.env.board_view("Mei") not in observation.situation
    for place in scheduler.env.world.places.values():
        if place.id != active.place:
            assert place.name not in observation.setting
    assert "08:00–12:00 and 14:00–18:00" in observation.setting
    scheduler.leave("Mei", "Pause")
    assert scheduler.observation("Mei").setting == unassigned.setting
    scheduler.select("Mei", base.choose("resume_work", target=active.id, seconds=3600))
    assert RULES in scheduler.observation("Mei").situation
    talking = scheduler.observation("Tomas")
    assert talking.setting == unassigned.setting and "UNRELATED_CHAT" in talking.situation


async def test_only_due_personal_appointment_is_kept(scheduler, monkeypatch):
    active = await assigned(scheduler, monkeypatch)
    scheduler.leave("Mei", "Arrange a meeting")
    for who in ("Tomas", "Aisha"):
        scheduler.env.move(who, "workshop", time=scheduler.now // 60)
    scheduler.invitation_action(
        "Mei",
        "invite",
        dict(
            people=["Tomas"],
            place="the Workshop",
            at="08:10",
            minutes=20,
            topic="DUE_MEETING",
            public=False,
        ),
    )
    invitation = next(iter(scheduler.invitations.values()))
    scheduler.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    scheduler.select("Mei", base.choose("resume_work", target=active.id, seconds=3600))
    # Notification text is retained as a percept; the standing list is focused on due meetings.
    before = scheduler.observation("Mei")
    assert "Your invitations/appointments:" not in before.situation
    scheduler.now = at(1, "08:10")
    assert "DUE_MEETING" in scheduler.observation("Mei").situation


async def test_latest_state_and_new_job_replace_old_task_view(scheduler, monkeypatch):
    active = await assigned(scheduler, monkeypatch)
    env = scheduler.env
    task = env.board.claim_of("Mei").task
    for accepted in (False, True):
        await env._submit(
            "Mei",
            SubmitWork(task_id=task.id, solution="patch", report="Ready"),
            time=scheduler.now // 60,
            place="workshop",
            scene="activities",
            prepared=(
                "patch",
                Assessment(passed=accepted, quality=float(accepted), feedback="LATEST_VERDICT"),
            ),
        )
        observation = scheduler.observation("Mei")
        assert ("REJECTED — rework required" in observation.situation) is (not accepted)
        if not accepted:
            assert task.parts[0].specification in observation.situation
        else:
            assert "ACCEPTED" in observation.situation
    # The claim was settled; Work without a job restores the board and town setting.
    assert observation.setting == scheduler.town_setting()
    await base.perform(scheduler, "Mei", "claim", job="task-2", partner=None)
    new = scheduler.observation("Mei")
    assert new.activity_task_id == "task-2" and active.task_id == "task-2"
    assert "Latest completed client verdict" not in new.situation
    assert env.board.claim_of("Mei").task.parts[0].specification in new.situation
    assert RULES in new.situation


@pytest.mark.parametrize("budget", [False, True])
async def test_actual_agent_keeps_task_rules_latest_logs_and_personal_method(
    scheduler, monkeypatch, tmp_path, budget
):
    await assigned(scheduler, monkeypatch)
    claim = scheduler.env.board.claim_of("Mei")
    required = "CURRENT_REQUIREMENT_START " + "requirement " * 50 + "CURRENT_REQUIREMENT_END"
    task = claim.task.model_copy(
        update={"parts": (claim.task.parts[0].model_copy(update={"specification": required}),)}
    )
    scheduler.env.board.claims[task.id] = claim.model_copy(update={"task": task})
    requests = []
    answers = iter(
        [
            {"thought": "Use method", "do": "use skill", "name": "check"},
            {"thought": "x" * 801, "do": "run local tests", "command": "true"},
            {"thought": "Check", "do": "run local tests", "command": "true"},
        ]
    )

    def reply(request):
        requests.append(request)
        text = "\n".join(m.content for m in request.messages)
        assert required in text and RULES in text
        assert "PERSONAL_GOAL" in text and "Mei" in request.messages[0].content
        assert "LATEST_RAW_FEEDBACK" + "z" * 1200 in text
        assert "RECENT_RAW_FEEDBACK" in text and "NEW_DIRECT_MESSAGE" in text
        assert "OLD_CAFE_MEMORY" not in text and "OLD_JOB_SUMMARY" not in text
        if budget:
            assert "Earlier original log omitted" in text
            assert request.metadata["context_usage"]["input_count"] <= 24000
        else:
            assert "OLDEST_RAW_FEEDBACK" in text
        if len(requests) >= 2:
            assert "SELECTED_METHOD" in text
        return next(answers)

    resident = Agent.create(
        tmp_path / "resident",
        SEED,
        ScriptedClient(reply),
        CognitionConfig(
            work_notes=WorkNotesConfig(enabled=True),
            context_budget=ContextBudgetConfig(enabled=budget, input_tokens=24000),
        ),
        TOWN,
    )
    scheduler.sim.agents["Mei"] = resident
    resident.parameters.write_policy("PERSONAL_GOAL")
    resident.memory.skills.write(
        Skill(name="check", title="Check", description="For repairs", body="SELECTED_METHOD")
    )
    resident.memory.episodic.append([Record(time=1, kind=EventKind.SPEECH, text="OLD_CAFE_MEMORY")])
    notes = resident.memory.work
    notes.record(task.id, 1, "observation", "OLDEST_RAW_FEEDBACK " + "a " * 12000)
    notes.record(task.id, 2, "observation", "RECENT_RAW_FEEDBACK")
    notes.observe(
        Percept(
            seq=10000,
            time=3,
            kind=EventKind.COMMAND_EXECUTED,
            task_id=task.id,
            text="LATEST_RAW_FEEDBACK" + "z" * 1200,
        )
    )
    notes.write_note(task.id, 4, "OLD_JOB_SUMMARY")
    scheduler.env.emit(
        EventKind.SPEECH,
        "NEW_DIRECT_MESSAGE",
        time=scheduler.now // 60,
        actor="Tomas",
        audience=["Mei"],
    )
    await resident.choose_tool(scheduler.observation("Mei"))
    assert len(requests) == 3 and requests[-1].after_invalid
    assert any(r.text == "OLD_CAFE_MEMORY" for r in resident.memory.episodic.read())
