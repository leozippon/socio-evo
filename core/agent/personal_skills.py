"""Optional personal methods, selected for one Activity and revised from owned experience."""

import json
from typing import Literal

from pydantic import Field

from core.agent import prompts
from core.agent.memory import Record, Skill
from core.agent.memory.skills import SKILL_NAME, name_of
from infrastructure.config import StrictModel


class UseSkill(StrictModel):
    thought: str = Field(max_length=1000)
    do: Literal["use skill"]
    name: str | None = Field(pattern=SKILL_NAME, max_length=64)


class ReviseSkill(StrictModel):
    thought: str = Field(max_length=1000)
    do: Literal["revise skill"]
    change: prompts.WriteSkill | prompts.RetireSkill
    sources: list[int] = Field(default_factory=list, max_length=12)
    """Optional witnessed event numbers, shown as source event N; never truth-log IDs."""


class PersonalSkills:
    def __init__(self, memory):
        self.memory = memory
        self.activity = None
        self.visit = None
        self.selected: Skill | None = None

    def enter(self, observation):
        # Selection decisions have no binding; a resumed Activity must select afresh.
        if (
            observation.activity_id is None
            or observation.activity_id != self.activity
            or observation.activity_visit_id != self.visit
        ):
            self.selected = None
        self.activity = observation.activity_id
        self.visit = observation.activity_visit_id

    def use(self, name, observation):
        selected = None
        if name is not None:
            selected = next((s for s in self.memory.skills.read() if s.name == name), None)
            if selected is None:
                raise ValueError("No such skill in your notebook; use a name from the directory.")
        self.selected = selected
        self.record(
            observation,
            f"You selected {selected.title!r} as a method to consider."
            if selected
            else "You stopped selecting a skill.",
            {"event": "selected", "skill": snapshot(selected)},
        )

    def revise(
        self,
        change,
        *,
        time,
        place=None,
        activity_id=None,
        activity_visit_id=None,
        task_id=None,
        sources=(),
        revision_id=None,
    ):
        if revision_id is not None and any(
            r.skill_trace.get("revision_id") == revision_id for r in self.memory.episodic.read()
        ):
            return
        known = {r.seq for r in self.memory.episodic.read() if r.time <= time}
        if any(source not in known for source in sources):
            raise ValueError("A source must be an event you have witnessed.")
        name = name_of(change.title)
        before = next((s for s in self.memory.skills.read() if s.name == name), None)
        after = None
        if isinstance(change, prompts.WriteSkill):
            after = Skill(
                name=name,
                title=change.title.strip(),
                description=change.summary,
                body=change.text.strip(),
            )
            self.memory.skills.write(after)
        else:
            self.memory.skills.remove(name)
        if self.selected is not None and self.selected.name == name:
            self.selected = after
        self.memory.episodic.append(
            [
                Record(
                    time=time,
                    place=place,
                    activity_id=activity_id,
                    activity_visit_id=activity_visit_id,
                    task_id=task_id,
                    text=f"You {'revised' if after else 'retired'} your method {change.title!r}.",
                    skill_trace={
                        "event": "revised" if after else "retired",
                        "before": snapshot(before),
                        "after": snapshot(after),
                        "sources": list(sources),
                        "revision_id": revision_id,
                    },
                )
            ]
        )

    def record(self, observation, text, trace):
        self.memory.episodic.append(
            [
                Record(
                    time=observation.time,
                    place=observation.place,
                    text=text,
                    activity_id=observation.activity_id,
                    activity_visit_id=observation.activity_visit_id,
                    task_id=observation.activity_task_id,
                    skill_trace=trace,
                )
            ]
        )


def snapshot(skill):
    return None if skill is None else {**skill.model_dump(), "version": skill.version}


def feedback_context(memory, now, *, activity_id=None, task_id=None, limit=6, include_methods=True):
    """Recorded associations, not causal scores; no extra model call or hidden results."""
    records = [r for r in memory.episodic.read() if r.time <= now]
    actions = [r for r in records if r.skill_trace.get("event") == "action"]
    if activity_id is not None or task_id is not None:
        actions = [
            r
            for r in actions
            if (
                (activity_id is not None and r.activity_id == activity_id)
                or (task_id is not None and r.task_id == task_id)
            )
        ]
    lines = []

    def observed(record):
        if record.task_id is not None:
            entry = next(
                (
                    e
                    for e in memory.work.entries(record.task_id, now)
                    if e["id"] == f"event:{record.seq}"
                ),
                None,
            )
            if entry is not None:
                return entry["text"]
        return record.text

    for action in actions[-limit:]:
        skill = action.skill_trace["skill"]
        outcomes = [r for r in records if action.decision_id in r.related_decisions]
        lines.append(
            f"Method {skill['title']} ({skill['version']}), decision {action.decision_id}: "
            + json.dumps(action.action, ensure_ascii=False)[:1000]
            + ("\nMethod at the time: " + skill["body"][:2000] if include_methods else "")
            + "\n"
            + (
                "\n".join(f"Source event {r.seq}: {observed(r)[:1000]}" for r in outcomes[-3:])
                or "No associated feedback has been observed yet."
            )
        )
    if not lines:
        return ""
    return (
        "Your method use and observed feedback (association does not establish that a method "
        "worked; local checks and client verdicts remain distinct):\n" + "\n\n".join(lines)
    )
