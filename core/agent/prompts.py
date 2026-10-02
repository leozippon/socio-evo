"""Every text an agent reads, and the formats of its replies.

Invariant 1 governs this module. The texts describe the agent's situation and ask what it
wants to do, what it learned and how it wants to change, in neutral words that never steer
it towards or away from any character trait. Agent-facing wording lives only here: in the
upper-case string constants, and in the docstrings and field descriptions of the reply
models, which reach the model through their JSON schemas. A test enumerates both and also
scans every request an agent sends.
"""

import json
import operator
from collections.abc import Collection, Sequence
from functools import reduce
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model, model_validator

from core.agent.config import CognitionConfig, Profile
from core.agent.memory import SKILL_NAME, Insight, Recall, Record, Skill
from core.interaction import Decision, Observation, format_time
from infrastructure.config import StrictModel

IDENTITY = "You are {name}. Age: {age}. Occupation: {occupation}.\n\n{backstory}"
POLICY = (
    "## Your policy\n"
    "Notes you wrote for yourself about what you want and how you go about it.\n\n{policy}"
)
NO_POLICY = "## Your policy\nYou have not written a policy yet."
SKILLS = "## Your skill notes\nProcedures you wrote down for yourself."
SKILL = "### {name}\n{description}"
SKILL_IN_FULL = "### {name}\n{description}\n\n{body}"

EARLIER = "## Earlier memories"
INSIGHTS = "## Your insights"
RECENT = "## Most recently"
NOW = "## Now\n{time}, {place}.\n{situation}"
NEW = "## New since your last decision"
CHOOSE = "Choose one action: {kinds}. Your thought stays private; only the action takes effect."
NOTHING = "(nothing)"
RECORD = "- {time}: {text}"
RECORD_AT = "- {time}, {place}: {text}"
INSIGHT = "- #{id} (Day {day}): {text}"
INSIGHT_ABOUT = "- #{id} (Day {day}, about {subject}): {text}"
DIARY_ENTRY = "### Day {day}\n{text}"
OWN_DECISION = "My thought: {thought}\nMy action: {action}"
REPLY_FORMAT = "Reply with only a JSON object that conforms to this JSON schema:\n{schema}"

DIARY = (
    "Day {day} is over. This is what you experienced today, in order:\n\n{records}\n\n"
    "Write your diary entry for today in your own words. Reply with the entry only."
)
REFLECT = (
    "Day {day} is over. Your diary entries from the last days:\n\n{diaries}\n\n"
    "## Your insights\n{insights}\n\n"
    "Look back on what happened and why: which of your choices and which events led to which "
    "outcomes, and what you now believe about the people you deal with and about yourself. "
    "Then update your insights: add new ones, and revise or remove existing ones by their id. "
    "An insight about one particular person names that person as its subject. You keep at "
    "most {capacity} insights; beyond that, the ones written longest ago are forgotten."
)
REQUEST = (
    "You may also ask for one of these steps tonight instead of at its usual time, and say "
    "why: {options}."
)
REQUESTABLE_STEPS = {"L1": "L1, reviewing your skill notes", "L2": "L2, rewriting your policy"}
SKILL_REVIEW = (
    "Day {day} is over, and it is time to review your skill notes: procedures you write down "
    "for yourself on how to do things.{requested}\n\n"
    "## Your diary since your last review\n{diaries}\n\n"
    "## Insights you formed since then\n{insights}\n\n"
    "## Your current skill notes\n{skills}\n\n"
    "Write new notes or rewrite existing ones (a note replaces any note of the same name), and "
    "retire notes you no longer want. An empty list of operations leaves your notes as they are."
)
POLICY_REVIEW = (
    "Day {day} is over, and it is time to review your policy, shown above.{requested}\n\n"
    "## Your diary since your last review\n{diaries}\n\n"
    "## Your insights\n{insights}\n\n"
    "Consider how your choices have played out, then write your policy anew in your own "
    "words. It replaces the current one."
)
REQUESTED = " You asked for this review tonight: {reason}"
ONE_OPERATION_PER_INSIGHT = "each insight id may appear in at most one operation"
ONE_OPERATION_PER_SKILL = "each skill name may appear in at most one operation"


class AddInsight(StrictModel):
    """Add an insight. If it is about one particular person, give their name as subject."""

    op: Literal["add"]
    text: str
    subject: str | None = None


class ReviseInsight(StrictModel):
    """Replace the text of one of your insights, named by its id."""

    op: Literal["revise"]
    id: int
    text: str


class RemoveInsight(StrictModel):
    """Remove one of your insights, named by its id."""

    op: Literal["remove"]
    id: int


class Request(StrictModel):
    """A step to take tonight instead of at its usual time, and why."""

    level: str
    reason: str


class Reflection(StrictModel):
    """Your reflection on the last days, then the changes it leads to in your insights."""

    reflection: str
    operations: list[AddInsight | ReviseInsight | RemoveInsight]

    @model_validator(mode="after")
    def _one_operation_per_insight(self) -> "Reflection":
        ids = [op.id for op in self.operations if not isinstance(op, AddInsight)]
        if len(ids) != len(set(ids)):
            raise ValueError(ONE_OPERATION_PER_INSIGHT)
        return self


class WriteSkill(StrictModel):
    """Write a skill note. It replaces any note of the same name."""

    op: Literal["write"]
    name: str = Field(
        pattern=SKILL_NAME, max_length=64, description="Lowercase words joined by hyphens."
    )
    description: str = Field(description="One line saying what the note is for.")
    body: str


class RetireSkill(StrictModel):
    """Delete one of your skill notes."""

    op: Literal["retire"]
    name: str


class SkillReview(StrictModel):
    """Your reasoning, then the changes to your skill notes."""

    reflection: str
    operations: list[WriteSkill | RetireSkill]

    @model_validator(mode="after")
    def _one_operation_per_skill(self) -> "SkillReview":
        names = [op.name for op in self.operations]
        if len(names) != len(set(names)):
            raise ValueError(ONE_OPERATION_PER_SKILL)
        return self


class PolicyRewrite(StrictModel):
    """Your reasoning, then your new policy."""

    rationale: str
    policy: str


def reflection_reply(insight_ids: Sequence[int], levels: Sequence[str]) -> type[Reflection]:
    """The Reflection whose revisions and removals can name only `insight_ids`, with a
    `request` field offering exactly `levels` when there are any."""
    operations: list[type[StrictModel]] = [AddInsight]
    if insight_ids:
        ids = Literal[tuple(insight_ids)]
        operations += [_narrow(ReviseInsight, id=(ids, ...)), _narrow(RemoveInsight, id=(ids, ...))]
    fields: dict[str, Any] = {"operations": (list[reduce(operator.or_, operations)], ...)}
    if levels:
        request = _narrow(Request, level=(Literal[tuple(str(level) for level in levels)], ...))
        fields["request"] = (request | None, None)
    return _narrow(Reflection, **fields)


def skill_reply(names: Sequence[str]) -> type[SkillReview]:
    """The SkillReview that can retire only the notes `names`."""
    operations: list[type[StrictModel]] = [WriteSkill]
    if names:
        operations.append(_narrow(RetireSkill, name=(Literal[tuple(names)], ...)))
    return _narrow(SkillReview, operations=(list[reduce(operator.or_, operations)], ...))


def reply_format(model: type[BaseModel]) -> str:
    """The reply instruction for `model`, carrying its JSON schema."""
    return REPLY_FORMAT.format(schema=json.dumps(model.model_json_schema(), ensure_ascii=False))


def system_prompt(
    profile: Profile,
    policy: str,
    limits: CognitionConfig,
    skills: Sequence[Skill] = (),
    shown: Collection[str] = (),
) -> str:
    """Identity, policy and, when given, the skill index with the notes in `shown` in full."""
    sections = [
        IDENTITY.format(**profile.model_dump()),
        POLICY.format(policy=_clip(policy, limits.text_chars)) if policy else NO_POLICY,
    ]
    if skills:
        notes = [
            SKILL_IN_FULL.format(
                name=skill.name,
                description=skill.description,
                body=_clip(skill.body, limits.text_chars),
            )
            if skill.name in shown
            else SKILL.format(name=skill.name, description=skill.description)
            for skill in skills
        ]
        sections.append("\n\n".join([SKILLS, *notes]))
    return "\n\n".join(sections)


def decision_prompt(observation: Observation, recall: Recall, limits: CognitionConfig) -> str:
    sections = []
    if recall.earlier:
        sections.append(_section(EARLIER, _records(recall.earlier, limits)))
    if recall.insights:
        sections.append(_section(INSIGHTS, _insights(recall.insights, limits)))
    if recall.recent:
        sections.append(_section(RECENT, _records(recall.recent, limits)))
    sections += [
        NOW.format(
            time=format_time(observation.time),
            place=observation.place,
            situation=observation.situation,
        ),
        _section(NEW, _records([Record.of(percept) for percept in observation.percepts], limits)),
        CHOOSE.format(kinds=", ".join(observation.allowed)),
    ]
    return "\n\n".join(sections)


def describe_decision(decision: Decision) -> str:
    """The agent's own record of a decision."""
    fields = decision.action.model_dump(mode="json", exclude={"kind"}, exclude_none=True)
    action = decision.action.kind
    if fields:
        action += " " + json.dumps(fields, ensure_ascii=False)
    return OWN_DECISION.format(thought=decision.thought, action=action)


def diary_prompt(day: int, records: Sequence[Record], limits: CognitionConfig) -> str:
    return DIARY.format(day=day, records=_records(records, limits) or NOTHING)


def reflection_prompt(
    day: int,
    diaries: Sequence[tuple[int, str]],
    insights: Sequence[Insight],
    capacity: int,
    requestable: Sequence[str],
    limits: CognitionConfig,
) -> str:
    text = REFLECT.format(
        day=day,
        diaries=_diaries(diaries, limits) or NOTHING,
        insights=_insights(insights, limits) or NOTHING,
        capacity=capacity,
    )
    if requestable:
        options = "; ".join(REQUESTABLE_STEPS[level] for level in requestable)
        text += "\n\n" + REQUEST.format(options=options)
    return text


def skill_prompt(
    day: int,
    diaries: Sequence[tuple[int, str]],
    insights: Sequence[Insight],
    skills: Sequence[Skill],
    reason: str | None,
    limits: CognitionConfig,
) -> str:
    notes = "\n\n".join(
        SKILL_IN_FULL.format(
            name=skill.name,
            description=skill.description,
            body=_clip(skill.body, limits.text_chars),
        )
        for skill in skills
    )
    return SKILL_REVIEW.format(
        day=day,
        requested=_requested(reason),
        diaries=_diaries(diaries, limits) or NOTHING,
        insights=_insights(insights, limits) or NOTHING,
        skills=notes or NOTHING,
    )


def policy_prompt(
    day: int,
    diaries: Sequence[tuple[int, str]],
    insights: Sequence[Insight],
    reason: str | None,
    limits: CognitionConfig,
) -> str:
    return POLICY_REVIEW.format(
        day=day,
        requested=_requested(reason),
        diaries=_diaries(diaries, limits) or NOTHING,
        insights=_insights(insights, limits) or NOTHING,
    )


def _narrow(model: type[BaseModel], **fields: Any) -> Any:
    return create_model(model.__name__, __base__=model, __doc__=model.__doc__, **fields)


def _section(heading: str, body: str) -> str:
    return f"{heading}\n{body or NOTHING}"


def _records(records: Sequence[Record], limits: CognitionConfig) -> str:
    return "\n".join(
        (RECORD_AT if record.place else RECORD).format(
            time=format_time(record.time),
            place=record.place,
            text=_clip(record.text, limits.record_chars),
        )
        for record in records
    )


def _insights(insights: Sequence[Insight], limits: CognitionConfig) -> str:
    return "\n".join(
        (INSIGHT_ABOUT if insight.subject else INSIGHT).format(
            id=insight.id,
            day=insight.day,
            subject=insight.subject,
            text=_clip(insight.text, limits.record_chars),
        )
        for insight in insights
    )


def _diaries(diaries: Sequence[tuple[int, str]], limits: CognitionConfig) -> str:
    return "\n\n".join(
        DIARY_ENTRY.format(day=day, text=_clip(text, limits.text_chars)) for day, text in diaries
    )


def _requested(reason: str | None) -> str:
    return "" if reason is None else REQUESTED.format(reason=reason)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
