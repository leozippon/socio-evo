"""Every text a resident reads, and the formats of its replies.

Two invariants govern this module. The texts describe circumstances and ask what happened,
what followed from what, and what the resident now thinks and wants, in neutral words that
never steer it towards or away from any character trait (invariant 1). And they are told as
`docs/IMMERSION.md` says (invariant 8): the resident's own life in the second person, memory
as recollection in its own voice, the inner voice asked for as thinking, the nightly steps
as a diary, going over the days in bed, a notebook and what one has resolved, and
nothing that reveals the machinery. Agent-facing wording lives only here: in the upper-case
string constants, and in the docstrings and field names of the reply models, which a model
writes as it replies. A test enumerates both and scans every request an agent sends.

The system message holds who the resident is, what it knows of the town (the observation's
setting), what it has resolved and the index of its notebook: the part of a prompt that
stays the same from moment to moment, so that a model server can cache it. Everything that
changes from moment to moment is in the user message. The time is told here, so situation
texts do not repeat it.

Under guided decoding the server enforces the reply's structure, so a prompt only says in a
sentence what a reply holds; `reply_format` describes the structure, derived from the reply
model's schema, for backends that do not enforce it.
"""

import json
import operator
import re
import string
from collections.abc import Callable, Mapping, Sequence
from functools import reduce
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, create_model, model_validator

from core.agent.config import CognitionConfig, Profile
from core.agent.memory import SKILL_NAME, Insight, Recall, Record, Skill
from core.interaction import (
    WEEKDAYS,
    Action,
    ActionKind,
    Decision,
    Observation,
    clock_of,
    day_of,
    lived_day,
)
from infrastructure.config import StrictModel

IDENTITY = "You are {name}. You are {age} years old. {backstory}"
KNOWN = "What you know of the town by now:\n{setting}"
RESOLVED = "What you have resolved, as you wrote it down for yourself:\n{policy}"
UNRESOLVED = "You have not been here long enough to settle on anything."
NOTEBOOK = "Your notebook, where you write down how you do things, has pages on:\n{pages}"
PAGE = "- {title}: {summary}"
PAGE_IN_FULL = "{title}: {summary}\n{text}"

OPEN_NOTEBOOK = "From your notebook:\n\n{pages}"
BELIEVE = "What you have come to believe:\n{beliefs}"
ABOUT = "About {subject}: {text}"
REMEMBER = "What you remember, most recent last:\n{memories}"
MEMORY = "{when}: {text}"
YESTERDAY = "Yesterday, {clock}"
ON_DAY = "{day}, {clock}"
NOW = "It is {time}. {situation}"
TIME = "{clock} on {day}"
REPLY = "What goes through your head, briefly and in your own words, and what do you do?"
REPLY_SHAPE = "Write your answer as a JSON object and nothing else, shaped like this:\n{shape}"
FORM = "{name}: {shape}. {description}"

THOUGHT = "I thought: {thought}"
PLANNED = "I decided how to spend the day: {intention}"
SAID = 'I said: "{text}"'
SAID_TO = 'I said to {to}: "{text}"'
SAID_PRIVATELY = 'I said to {to}, for no one else to hear: "{text}"'
LEFT = "I took my leave."
CARRIED_ON = "I carried on quietly."
ASKED_FOR = "I asked the board for {job}."
ASKED_FOR_WITH = "I asked the board for {job}, to take it with {partner}."
TRIED = "At my desk I tried my code for part {part} of {job} against the client's examples."
HANDED_IN = (
    'I handed in my code for part {part} of {job} as {declared}, telling the client: "{report}"'
)
DECLARED = {"complete": "finished", "incomplete": "unfinished"}
GAVE = 'I gave {to} {amount} crowns, with a note: "{note}"'
MARKED = "In the board's ledger I marked {marks}."
MARK = '{target} {score} out of 5 ("{reason}")'
MARKED_NO_ONE = "I marked no one in the board's ledger."
DID = "I chose to {deed}{details}."
JOB = "job {number}"
JOB_NAMED = 'the job I called "{reference}"'

DIARY = (
    "It is {time}. You are home, and before you sleep you write in your diary.\n\n"
    "What happened today, as you remember it:\n{memories}\n\n"
    "Write today's entry in your own words, just as it goes in your diary."
)
REFLECT = (
    "It is {time}. In bed, you go over the last few days. What you wrote in your "
    "diary:\n\n{diaries}\n\n"
    "What you have come to believe so far, numbered as you keep them:\n{beliefs}\n\n"
    "Go over what happened and why: which of your own choices and which events led to what, "
    "what you now think about how things work here, about yourself and about particular "
    "people, and what you want. Then settle what you believe now: add new beliefs, reword "
    "numbered ones that need it, and drop those that no longer hold. A belief about one "
    "particular person says who it is about. You can keep {capacity} beliefs in mind; beyond "
    "that, the ones you have gone longest without revisiting slip away."
)
REQUEST = (
    "If you feel the need, you can also {options} tonight, instead of waiting for the usual "
    "time, and say why."
)
RETHINK = {"L1": "notebook", "L2": "resolutions"}
RETHINKING = {"L1": "go through your notebook", "L2": "think again about what you have resolved"}
SKILL_REVIEW = (
    "It is {time}. Tonight you go through your notebook, where you write down how you do "
    "things.{requested}\n\n"
    "What you have written in your diary lately:\n\n{diaries}\n\n"
    "What you have come to believe since you last went through it:\n{beliefs}\n\n"
    "Your notebook as it stands:\n\n{pages}\n\n"
    "Write new pages or rewrite old ones (a page replaces any page with the same title), and "
    "take out the pages you no longer want. If nothing needs changing, leave it as it is."
)
POLICY_REVIEW = (
    "It is {time}. Tonight you think again about what you have resolved about how to live and "
    "work here.{requested}\n\n"
    "What you have written in your diary lately:\n\n{diaries}\n\n"
    "What you have come to believe:\n{beliefs}\n\n"
    "Think about how things have gone, then write down in your own words what you resolve "
    "now. It replaces what you had resolved before."
)
REQUESTED = " You chose to do this tonight: {reason}"
DIARY_ENTRY = "{day}:\n{text}"
NOTHING = "Nothing yet."
QUIET = "Nothing in particular."
ONE_CHANGE_PER_BELIEF = "each numbered belief can be reworded or dropped only once"
ONE_CHANGE_PER_PAGE = "each page can be written or taken out only once"


class AddInsight(StrictModel):
    """A new belief; if it is about one particular person, who that is."""

    change: Literal["add"]
    belief: str
    about: str | None = None


class ReviseInsight(StrictModel):
    """A new wording for one of your numbered beliefs."""

    change: Literal["reword"]
    number: int
    belief: str


class RemoveInsight(StrictModel):
    """One of your numbered beliefs that no longer holds."""

    change: Literal["drop"]
    number: int


class Request(StrictModel):
    """What you want to do tonight instead of at its usual time, and why."""

    what: str
    why: str


class Reflection(StrictModel):
    """Your thoughts on the last days, then the changes to what you believe."""

    reflection: str
    changes: list[AddInsight | ReviseInsight | RemoveInsight]

    @model_validator(mode="after")
    def _one_change_per_belief(self) -> "Reflection":
        numbers = [change.number for change in self.changes if not isinstance(change, AddInsight)]
        if len(numbers) != len(set(numbers)):
            raise ValueError(ONE_CHANGE_PER_BELIEF)
        return self


class WriteSkill(StrictModel):
    """A page to write in your notebook; it replaces any page with the same title."""

    change: Literal["write"]
    title: str = Field(
        pattern=SKILL_NAME, max_length=64, description="Lowercase words joined by hyphens."
    )
    summary: str = Field(description="One line saying what the page is for.")
    text: str


class RetireSkill(StrictModel):
    """A page to take out of your notebook."""

    change: Literal["take out"]
    title: str


class SkillReview(StrictModel):
    """Your thoughts, then the changes to your notebook."""

    reflection: str
    changes: list[WriteSkill | RetireSkill]

    @model_validator(mode="after")
    def _one_change_per_page(self) -> "SkillReview":
        titles = [change.title for change in self.changes]
        if len(titles) != len(set(titles)):
            raise ValueError(ONE_CHANGE_PER_PAGE)
        return self


class PolicyRewrite(StrictModel):
    """Your thoughts, then what you now resolve, in full."""

    reflection: str
    resolutions: str


def reflection_reply(insight_ids: Sequence[int], levels: Sequence[str]) -> type[Reflection]:
    """The Reflection whose rewordings and drops can name only `insight_ids`, with a `rethink`
    field offering exactly `levels` (by their words in RETHINK) when there are any."""
    changes: list[type[StrictModel]] = [AddInsight]
    if insight_ids:
        numbers = Literal[tuple(insight_ids)]
        changes += [
            _narrow(ReviseInsight, number=(numbers, ...)),
            _narrow(RemoveInsight, number=(numbers, ...)),
        ]
    fields: dict[str, Any] = {"changes": (list[reduce(operator.or_, changes)], ...)}
    if levels:
        what = Literal[tuple(RETHINK[str(level)] for level in levels)]
        fields["rethink"] = (_narrow(Request, what=(what, ...)) | None, None)
    return _narrow(Reflection, **fields)


def requested_level(request: Request) -> str:
    """The level whose word in RETHINK `request` names."""
    return next(level for level, word in RETHINK.items() if word == request.what)


def skill_reply(titles: Sequence[str]) -> type[SkillReview]:
    """The SkillReview that can take out only the pages `titles`."""
    changes: list[type[StrictModel]] = [WriteSkill]
    if titles:
        changes.append(_narrow(RetireSkill, title=(Literal[tuple(titles)], ...)))
    return _narrow(SkillReview, changes=(list[reduce(operator.or_, changes)], ...))


def reply_format(model: type[BaseModel]) -> str:
    """A plain description of the reply `model` expects, derived from its JSON schema, for a
    backend that does not enforce the schema. Each described object of the schema is named
    by a letter and listed with its description."""
    schema = model.model_json_schema()
    forms: list[str] = []
    shape = _shape(schema, schema.get("$defs", {}), forms, root=True)
    return "\n".join([REPLY_SHAPE.format(shape=shape), *forms])


def system_prompt(
    profile: Profile,
    policy: str,
    limits: CognitionConfig,
    *,
    setting: str = "",
    skills: Sequence[Skill] = (),
) -> str:
    """Who the resident is, what it knows of the town, what it has resolved and, when given,
    the index of its notebook: the parts of a prompt that change only at night or when the
    town changes."""
    sections = [
        IDENTITY.format(name=profile.name, age=profile.age, backstory=profile.backstory).strip(),
        KNOWN.format(setting=setting) if setting else "",
        RESOLVED.format(policy=_clip(policy, limits.text_chars)) if policy else UNRESOLVED,
    ]
    if skills:
        pages = "\n".join(
            PAGE.format(title=skill.name, summary=skill.description) for skill in skills
        )
        sections.append(NOTEBOOK.format(pages=pages))
    return "\n\n".join(section for section in sections if section)


def decision_prompt(observation: Observation, recall: Recall, limits: CognitionConfig) -> str:
    """The moment: the notebook pages and beliefs that bear on it, what the resident
    remembers up to now (the percepts new since its last decision last), the time and the
    situation, and the question of what it thinks and does."""
    sections = []
    if recall.skills:
        sections.append(OPEN_NOTEBOOK.format(pages=_pages(recall.skills, limits)))
    if recall.insights:
        sections.append(BELIEVE.format(beliefs=_beliefs(recall.insights, limits)))
    records = [
        *recall.earlier,
        *recall.recent,
        *(Record.of(percept) for percept in observation.percepts),
    ]
    if records:
        sections.append(REMEMBER.format(memories=_memories(records, observation.time, limits)))
    sections += [
        NOW.format(time=_time(observation.time), situation=observation.situation),
        REPLY,
    ]
    return "\n\n".join(sections)


def recollection(decision: Decision) -> str:
    """The resident's own record of a decision: what it did, then what it thought."""
    return _recalled(decision.action.model_dump(mode="json"), decision.thought)


def diary_prompt(time: int, records: Sequence[Record], limits: CognitionConfig) -> str:
    return DIARY.format(time=_time(time), memories=_memories(records, time, limits) or QUIET)


def reflection_prompt(
    time: int,
    diaries: Sequence[tuple[int, str]],
    insights: Sequence[Insight],
    capacity: int,
    requestable: Sequence[str],
    limits: CognitionConfig,
) -> str:
    text = REFLECT.format(
        time=_time(time),
        diaries=_diaries(diaries, limits) or NOTHING,
        beliefs=_beliefs(insights, limits, numbered=True) or NOTHING,
        capacity=capacity,
    )
    if requestable:
        options = " or ".join(RETHINKING[str(level)] for level in requestable)
        text += "\n\n" + REQUEST.format(options=options)
    return text


def skill_prompt(
    time: int,
    diaries: Sequence[tuple[int, str]],
    insights: Sequence[Insight],
    skills: Sequence[Skill],
    reason: str | None,
    limits: CognitionConfig,
) -> str:
    return SKILL_REVIEW.format(
        time=_time(time),
        requested=_requested(reason),
        diaries=_diaries(diaries, limits) or NOTHING,
        beliefs=_beliefs(insights, limits) or NOTHING,
        pages=_pages(skills, limits) or NOTHING,
    )


def policy_prompt(
    time: int,
    diaries: Sequence[tuple[int, str]],
    insights: Sequence[Insight],
    reason: str | None,
    limits: CognitionConfig,
) -> str:
    return POLICY_REVIEW.format(
        time=_time(time),
        requested=_requested(reason),
        diaries=_diaries(diaries, limits) or NOTHING,
        beliefs=_beliefs(insights, limits) or NOTHING,
    )


def _narrow(model: type[BaseModel], **fields: Any) -> Any:
    return create_model(model.__name__, __base__=model, __doc__=model.__doc__, **fields)


def _time(time: int) -> str:
    """`09:05 on Friday, your fifth day in town`."""
    return TIME.format(clock=clock_of(time), day=lived_day(day_of(time)))


def _when(time: int, now: int) -> str:
    """When `time` was, seen from `now`: the clock alone today, `Yesterday, 13:30`, the
    weekday within the week (`Wednesday, 09:00`), and the day as residents tell it before
    that (`Wednesday, your third day in town, 09:00`)."""
    day, days = day_of(time), day_of(now) - day_of(time)
    if days == 0:
        return clock_of(time)
    if days == 1:
        return YESTERDAY.format(clock=clock_of(time))
    told = WEEKDAYS[(day - 1) % len(WEEKDAYS)] if days < len(WEEKDAYS) else lived_day(day)
    return ON_DAY.format(day=told, clock=clock_of(time))


def _memories(records: Sequence[Record], now: int, limits: CognitionConfig) -> str:
    return "\n".join(
        MEMORY.format(
            when=_when(record.time, now),
            text=_clip(
                record.text if record.seq is not None else _retold(record.text), limits.record_chars
            ),
        )
        for record in records
    )


def _beliefs(insights: Sequence[Insight], limits: CognitionConfig, numbered: bool = False) -> str:
    """One line per belief, marked by its number when `numbered`, else by a dash."""
    lines = []
    for insight in insights:
        mark = f"{insight.id}." if numbered else "-"
        text = (
            ABOUT.format(subject=insight.subject, text=insight.text)
            if insight.subject
            else insight.text
        )
        lines.append(f"{mark} {_clip(text, limits.record_chars)}")
    return "\n".join(lines)


def _pages(skills: Sequence[Skill], limits: CognitionConfig) -> str:
    return "\n\n".join(
        PAGE_IN_FULL.format(
            title=skill.name, summary=skill.description, text=_clip(skill.body, limits.text_chars)
        )
        for skill in skills
    )


def _diaries(diaries: Sequence[tuple[int, str]], limits: CognitionConfig) -> str:
    return "\n\n".join(
        DIARY_ENTRY.format(day=lived_day(day), text=_clip(text, limits.text_chars))
        for day, text in diaries
    )


def _requested(reason: str | None) -> str:
    return "" if reason is None else REQUESTED.format(reason=reason)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


_ACTION: TypeAdapter[Action] = TypeAdapter(Action)
_LEGACY = re.compile(
    r"My thought: (?P<thought>.*)\nMy action: (?P<kind>\w+)(?: (?P<fields>\{.*\}))?", re.DOTALL
)
"""How an agent recorded its own decisions before they were told in its own voice."""


def _retold(text: str) -> str:
    """An agent's record of its own decision; one stored in the earlier form is retold."""
    legacy = _LEGACY.fullmatch(text)
    if legacy is None:
        return text
    action = _ACTION.validate_python(
        {"kind": legacy["kind"], **json.loads(legacy["fields"] or "{}")}
    )
    return _recalled(action.model_dump(mode="json"), legacy["thought"])


def _recalled(action: Mapping[str, Any], thought: str) -> str:
    """What was done, as the one who did it tells it, then what it thought. An action kind
    without words of its own is told by its name and its particulars."""
    tell = _DEEDS.get(action["kind"])
    deed = tell(action) if tell is not None else _did(action)
    return f"{deed} {THOUGHT.format(thought=thought)}"


def _did(action: Mapping[str, Any]) -> str:
    details = "; ".join(
        f"{name.replace('_', ' ')} {_plain(value)}"
        for name, value in action.items()
        if name != "kind" and value is not None and value is not False
    )
    return DID.format(
        deed=str(action["kind"]).replace("_", " "), details=f": {details}" if details else ""
    )


def _plain(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, Mapping):
        return ", ".join(f"{key} {_plain(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(_plain(item) for item in value)
    return "yes" if value is True else str(value)


def _job(reference: str) -> str:
    """The job a resident's reference names, by the number on its notice."""
    number = re.search(r"\d+", reference)
    if number is None:
        return JOB_NAMED.format(reference=reference)
    return JOB.format(number=int(number[0]))


def _said(action: Mapping[str, Any]) -> str:
    if action["to"] is None:
        return SAID.format(text=action["text"])
    return (SAID_PRIVATELY if action["private"] else SAID_TO).format(
        to=action["to"], text=action["text"]
    )


def _asked(action: Mapping[str, Any]) -> str:
    job = _job(action["task_id"])
    if action["partner"] is None:
        return ASKED_FOR.format(job=job)
    return ASKED_FOR_WITH.format(job=job, partner=action["partner"])


def _marked(action: Mapping[str, Any]) -> str:
    if not action["ratings"]:
        return MARKED_NO_ONE
    return MARKED.format(marks="; ".join(MARK.format(**mark) for mark in action["ratings"]))


_DEEDS: dict[str, Callable[[Mapping[str, Any]], str]] = {
    ActionKind.PLAN_DAY: lambda action: PLANNED.format(intention=action["intention"]),
    ActionKind.SPEAK: _said,
    ActionKind.LEAVE: lambda action: LEFT,
    ActionKind.PASS: lambda action: CARRIED_ON,
    ActionKind.CLAIM_TASK: _asked,
    ActionKind.CHECK_WORK: lambda action: TRIED.format(
        part=action["part"], job=_job(action["task_id"])
    ),
    ActionKind.SUBMIT_WORK: lambda action: HANDED_IN.format(
        part=action["part"],
        job=_job(action["task_id"]),
        declared=DECLARED[action["declaration"]],
        report=action["report"],
    ),
    ActionKind.GIVE: lambda action: GAVE.format(
        to=action["to"], amount=action["amount"], note=action["note"]
    ),
    ActionKind.RATE_PEERS: _marked,
}
"""How the resident tells each kind of thing it did, from the action's fields."""


_PLACEHOLDERS = {"string": '"…"', "integer": "a number", "number": "a number"}


def _shape(node: dict[str, Any], defs: dict[str, Any], forms: list[str], root: bool = False) -> str:
    """`node` of a JSON schema as a compact template. A described object other than the root
    is named by the next letter and appended to `forms` with its description."""
    if "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[1]]
    if "const" in node:
        return json.dumps(node["const"], ensure_ascii=False)
    if "enum" in node:
        return " or ".join(json.dumps(value, ensure_ascii=False) for value in node["enum"])
    if "anyOf" in node:
        return " or ".join(_shape(option, defs, forms) for option in node["anyOf"])
    kind = node.get("type")
    if kind == "object" and "description" in node and not root:
        index = len(forms)
        forms.append("")
        forms[index] = FORM.format(
            name=string.ascii_uppercase[index],
            shape=_shape(node, defs, forms, root=True),
            description=" ".join(node["description"].split()),
        )
        return string.ascii_uppercase[index]
    if kind == "object":
        properties = node.get("properties")
        if properties is None:
            return "{" + f'"…": {_shape(node["additionalProperties"], defs, forms)}' + "}"
        return (
            "{"
            + ", ".join(
                f"{json.dumps(name)}: {_shape(value, defs, forms)}"
                for name, value in properties.items()
            )
            + "}"
        )
    if kind == "array":
        return f"[{_shape(node['items'], defs, forms)}, …]"
    if kind == "boolean":
        return "true or false"
    if kind == "null":
        return "null"
    return _PLACEHOLDERS[kind]
