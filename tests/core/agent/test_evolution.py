import pytest
from pydantic import ValidationError

from core.agent import Agent, CognitionConfig
from core.agent.evolution import (
    EvolutionConfig,
    Evolver,
    History,
    Level,
    SelfTrigger,
    Trigger,
    commit_date,
)
from core.interaction import day_of, time_at
from infrastructure.config import ConfigError
from infrastructure.git import Repository

L0, L1, L2 = Level.L0, Level.L1, Level.L2
DAILY, WEEKLY, MONTHLY, SELF = Trigger.DAILY, Trigger.WEEKLY, Trigger.MONTHLY, Trigger.SELF


def _end(day: int) -> int:
    return time_at(day, "22:00")


def _changed(repository: Repository, commit: str) -> set[str]:
    return {
        line[6:]
        for line in repository.diff(f"{commit}^", commit).splitlines()
        if line.startswith(("--- a/", "+++ b/"))
    }


async def test_days_weeks_and_a_month_become_one_commit_per_step(agent, script, observe):
    evolver = Evolver(
        EvolutionConfig(self_trigger=SelfTrigger(enabled=False), retention_days=2, max_insights=2)
    )
    history = History(agent.path)
    script.reflections = {
        1: [{"change": "add", "belief": "Ben asks about parsers.", "about": "Ben"}],
        2: [
            {"change": "reword", "number": 1, "belief": "Ben asks about parsers every day."},
            {"change": "add", "belief": "Mornings are quiet."},
        ],
        3: [{"change": "add", "belief": "Answering quickly brings more questions."}],
        4: [{"change": "drop", "number": 3}],
    }
    script.skills = {
        2: [{"change": "write", "title": "date-parsing", "summary": "Dates.", "text": "ISO."}],
        4: [
            {"change": "take out", "title": "date-parsing"},
            {"change": "write", "title": "answering", "summary": "Replies.", "text": "Brief."},
        ],
    }
    plan = {1: (DAILY,), 2: (DAILY, WEEKLY), 3: (DAILY, MONTHLY), 4: (DAILY, WEEKLY)}
    committed = []
    for day, triggers in plan.items():
        await agent.act(observe(day))
        history.commit_experience(_end(day))
        for trigger in triggers:
            committed += await evolver.evolve(agent, trigger, _end(day))

    versions = history.log()[::-1]
    assert [(v.level, v.trigger, v.time) for v in versions] == [
        (None, None, 0),
        (None, None, _end(1)),
        (L0, DAILY, _end(1)),
        (None, None, _end(2)),
        (L0, DAILY, _end(2)),
        (L1, WEEKLY, _end(2)),
        (None, None, _end(3)),
        (L0, DAILY, _end(3)),
        (L2, MONTHLY, _end(3)),
        (None, None, _end(4)),
        (L0, DAILY, _end(4)),
        (L1, WEEKLY, _end(4)),
    ]
    assert committed == [version for version in versions if version.level is not None]

    repository = Repository(agent.path)
    commits = repository.log()[::-1]
    assert [commit.date for commit in commits] == [commit_date(v.time) for v in versions]
    assert commits[-1].body == f"Notebook 4.\n\nLevel: L1\nTrigger: weekly\nSim-Time: {_end(4)}"
    assert (versions[-1].subject, versions[-1].body) == (
        "Review skills on Day 4",
        "Notebook 4.",
    )
    assert versions[8].body == "Thoughts 3."
    assert _changed(repository, versions[1].commit) == {"memory/episodic.jsonl"}
    assert _changed(repository, versions[2].commit) == {
        "memory/diary/day-0001.md",
        "memory/insights.jsonl",
    }
    assert _changed(repository, versions[8].commit) == {"parameters/policy.md"}

    first_review, second_review = script.prompts("skills")
    assert "Diary entry 1." in first_review and "Diary entry 2." in first_review
    assert "Diary entry 2." not in second_review and "Diary entry 4." in second_review

    assert agent.parameters.read_policy() == "Resolutions 3."
    assert [skill.name for skill in agent.memory.skills.read()] == ["answering"]
    assert [(i.id, i.day, i.text) for i in agent.memory.insights.read()] == [
        (2, 2, "Mornings are quiet.")
    ]
    assert {day_of(record.time) for record in agent.memory.episodic.read()} == {3, 4}
    assert [day for day, _ in agent.memory.diary.entries()] == [1, 2, 3, 4]

    history.reset(versions[5].commit)
    assert history.head() == versions[5].commit
    assert agent.parameters.read_policy() == ""
    assert [day for day, _ in agent.memory.diary.entries()] == [1, 2]
    assert [skill.name for skill in agent.memory.skills.read()] == ["date-parsing"]


async def test_reflection_may_request_a_deeper_step_subject_to_the_cooldown(agent, script):
    evolver = Evolver(EvolutionConfig(self_trigger=SelfTrigger(levels=(L2,), cooldown_days=2)))
    script.request = {"what": "resolutions", "why": "My plans changed."}
    for day in range(1, 5):
        await evolver.evolve(agent, DAILY, _end(day))
        if day == 3:
            assert await evolver.evolve(agent, MONTHLY, _end(day)) == []

    log = History(agent.path).log()
    assert [(v.level, v.trigger, day_of(v.time)) for v in reversed(log) if v.level] == [
        (L0, DAILY, 1),
        (L2, SELF, 1),
        (L0, DAILY, 2),
        (L0, DAILY, 3),
        (L2, SELF, 3),
        (L0, DAILY, 4),
    ]
    offered = [
        "rethink" in r.json_schema["properties"]
        for r in script.requests
        if r.metadata["purpose"] == "reflect"
    ]
    assert offered == [True, False, True, False]
    assert log[1].body == "Requested: My plans changed.\n\nThoughts 3."
    assert "You chose to do this tonight: My plans changed." in script.prompts("policy")[1]


async def test_a_step_that_changes_nothing_still_counts_as_applied(agent, script):
    evolver = Evolver(EvolutionConfig())
    script.request = {"what": "notebook", "why": "I want to look at my notes."}
    returned = await evolver.evolve(agent, DAILY, _end(1))
    assert await evolver.evolve(agent, WEEKLY, _end(1)) == []
    for day in (2, 3):
        returned += await evolver.evolve(agent, DAILY, _end(day))

    steps = [version for version in History(agent.path).log()[::-1] if version.level]
    assert [(v.level, v.trigger, day_of(v.time)) for v in steps] == [
        (L0, DAILY, 1),
        (L1, SELF, 1),
        (L0, DAILY, 2),
        (L0, DAILY, 3),
    ]
    assert returned == steps
    assert len(script.prompts("skills")) == 1
    review = steps[1].commit
    assert Repository(agent.path).diff(f"{review}^", review) == ""


async def test_with_every_level_disabled_only_experience_is_recorded(agent, script, observe):
    evolver = Evolver(EvolutionConfig(levels=()))
    await agent.act(observe(1))
    for trigger in (DAILY, WEEKLY, MONTHLY):
        assert await evolver.evolve(agent, trigger, _end(1)) == []
    with pytest.raises(ValueError):
        await evolver.evolve(agent, SELF, _end(1))
    assert [request.metadata["purpose"] for request in script.requests] == ["act"]

    history = History(agent.path)
    assert len(history.log()) == 1
    version = history.commit_experience(_end(1))
    assert (version.level, version.trigger, version.time) == (None, None, _end(1))
    assert history.commit_experience(_end(1)) is None


def test_unimplemented_or_misplaced_levels_are_configuration_errors():
    with pytest.raises(ConfigError, match="L3"):
        Evolver(EvolutionConfig(levels=(L0, Level.L3)))
    with pytest.raises(ValidationError):
        EvolutionConfig(schedule={SELF: (L1,)})
    with pytest.raises(ValidationError):
        SelfTrigger(levels=(L0,))


async def test_a_frozen_export_loads_without_history_and_stays_independent(
    agent, script, observe, tmp_path
):
    evolver = Evolver(EvolutionConfig())
    history = History(agent.path)
    await evolver.evolve(agent, MONTHLY, _end(1))
    history.tag("day-0001")
    path = tmp_path / "evaluation" / "Mei-day-0001"
    history.export("day-0001", path)
    frozen = Agent.load(path, script.client, CognitionConfig())
    assert not (path / ".git").exists()
    assert frozen.parameters.read_policy() == "Resolutions 1."

    await evolver.evolve(agent, MONTHLY, _end(2))
    await frozen.act(observe(3))
    assert frozen.parameters.read_policy() == "Resolutions 1."
    assert agent.parameters.read_policy() == "Resolutions 2."
    assert len(frozen.memory.episodic.read()) == 2
    assert agent.memory.episodic.read() == []
