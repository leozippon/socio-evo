"""The answer card: what a resident can do at a moment, in the town's words.

A moment's `Observation.allowed` holds an allowance for each kind of thing the resident can
do now, with the values that are really possible: the jobs on the board, the people present,
the parts of its own job, the places open in each part of the day. One definition turns the
allowances into the forms of a reply, and the forms into three things that cannot disagree:
the card a resident reads, the JSON schema of the same forms that every reply is validated
against (and that a server may enforce under guided decoding), and the translation of a
reply into the `Decision` the town carries out. `correction` tells a resident whose answer
could not be read what was wrong, in the card's words. Every form opens with the resident's
thought and then says what it does (`do`) in plain words, with fields named and valued as
the town names them, so the code's names for actions and fields never reach a resident, not
even in what it writes.

The wording here is agent-facing: invariant 1 and invariant 8 (`docs/IMMERSION.md`) govern it,
and tests scan the upper-case constants and every card. Each action kind has exactly one
allowance class in ALLOWANCES, so a kind added later cannot be offered before it has one, and
a test fails until it does. `form` writes out the reply of any model, so the agent's nightly
replies are shown the same way.
"""

import json
import string
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, Field, RootModel, ValidationError, create_model, model_validator

from core.interaction.actions import (
    Action,
    ActionKind,
    CheckWork,
    ClaimTask,
    Decision,
    Declaration,
    Give,
    Leave,
    PartNumber,
    Pass,
    PeerRating,
    PlanDay,
    RatePeers,
    Speak,
    SubmitWork,
    Vote,
    job_number,
)
from infrastructure.config import StrictModel

DECIDE = "decide the day"
SAY = "say"
SAY_PRIVATELY = "say privately"
LEAVE = "go home for the rest of this part of the day"
CARRY_ON = "carry on quietly"
TAKE = "take a job"
TAKE_FOR_TWO = "take a job for two"
PUT_NAME_DOWN = "put your name down for a job for two"
TRY = "try your code"
HAND_IN = "hand in"
HAND_OVER = "hand over money"
MARK = "mark people in the ledger"
GIVE_ANSWER = "give the clerk your answer"

THOUGHT = "thought"
DOES = "do"
PLAN = "plan"
TO = "to"
WORDS = "words"
JOB = "job"
WITH = "with"
PART = "part"
CODE = "code"
AS = "as"
TELLING = "telling the client"
NOTE = "note"
MARKS = "marks"
REPLY_GIVEN = "answer"
WHO = "who"
MARK_GIVEN = "mark"
BECAUSE = "because"
EVERYONE = "for everyone"
DECLARED = {Declaration.COMPLETE: "finished", Declaration.INCOMPLETE: "unfinished"}

ANSWER = "Answer in this form:"
ANSWERS = "Answer in one of these forms:"
NOTED = "{name}: {shape}. {description}"
TEXT = '"…"'
NUMBER = "a whole number"
TRUTH = "true or false"
NOTHING = "null"
MORE = "…"

UNREAD = "That answer could not be read: {problems}. Answer again, written as shown above."
UNREADABLE = (
    "That answer could not be read as it was written. Answer again, written as shown above."
)
MISSING = '"{key}" is missing'
NOT_IN_FORM = '"{key}" is not part of that form'
NOT_A_CHOICE = '"{key}" is not one of the choices shown'
NOT_AS_SHOWN = '"{key}" is not written as shown'

Fields = dict[str, tuple[Any, str | None]]
"""A form's fields after `thought` and `do`: its key, as the resident writes it, to the type
of its value and an optional word on it."""


@dataclass(frozen=True)
class _Form:
    does: str
    fields: Fields
    action: Callable[[Mapping[str, Any]], Action]
    """The action a reply in this form means, from the reply's fields by key."""


class _Allowance(StrictModel):
    def forms(self) -> list[_Form]:
        raise NotImplementedError


class MayPlan(_Allowance):
    """Deciding where to spend each part of the day: for each part, by its name, the places
    the resident can name, each by the name it knows it by, with the place's id."""

    kind: Literal[ActionKind.PLAN_DAY] = ActionKind.PLAN_DAY
    places: dict[str, dict[str, str]] = Field(min_length=1)

    def forms(self) -> list[_Form]:
        fields: Fields = {part: (_one_of(names), None) for part, names in self.places.items()}
        fields[PLAN] = (str, None)

        def plan(reply: Mapping[str, Any]) -> Action:
            itinerary = {part: names[reply[part]] for part, names in self.places.items()}
            return PlanDay(itinerary=itinerary, intention=reply[PLAN])

        return [_Form(DECIDE, fields, plan)]


class MaySpeak(_Allowance):
    """Saying something to the people present, aloud or privately to one of them."""

    kind: Literal[ActionKind.SPEAK] = ActionKind.SPEAK
    to: tuple[str, ...] = Field(min_length=1)

    def forms(self) -> list[_Form]:
        people = _one_of(self.to)
        return [
            _Form(
                SAY,
                {TO: (people | None, EVERYONE), WORDS: (str, None)},
                lambda reply: Speak(text=reply[WORDS], to=reply[TO]),
            ),
            _Form(
                SAY_PRIVATELY,
                {TO: (people, None), WORDS: (str, None)},
                lambda reply: Speak(text=reply[WORDS], to=reply[TO], private=True),
            ),
        ]


class MayLeave(_Allowance):
    """Leaving the place for home, for the rest of this part of the day."""

    kind: Literal[ActionKind.LEAVE] = ActionKind.LEAVE

    def forms(self) -> list[_Form]:
        return [_Form(LEAVE, {}, lambda reply: Leave())]


class MayPass(_Allowance):
    """Carrying on quietly."""

    kind: Literal[ActionKind.PASS] = ActionKind.PASS

    def forms(self) -> list[_Form]:
        return [_Form(CARRY_ON, {}, lambda reply: Pass())]


class MayClaim(_Allowance):
    """Taking a job from the board: the ids of the jobs for one (`alone`) and for two
    (`together`) on it, and the neighbours who can be named for a job for two, or None when
    the clerk pairs the names put down for them by lot."""

    kind: Literal[ActionKind.CLAIM_TASK] = ActionKind.CLAIM_TASK
    alone: tuple[str, ...] = ()
    together: tuple[str, ...] = ()
    partners: tuple[str, ...] | None

    @model_validator(mode="after")
    def _something_to_take(self) -> "MayClaim":
        if not self.forms():
            raise ValueError("no job can be taken")
        return self

    def forms(self) -> list[_Form]:
        forms = []
        if self.alone:
            ids = {job_number(task): task for task in self.alone}
            forms.append(
                _Form(
                    TAKE,
                    {JOB: (_one_of(ids), None)},
                    lambda reply: ClaimTask(task_id=ids[reply[JOB]]),
                )
            )
        if self.together and self.partners is None:
            pairs = {job_number(task): task for task in self.together}
            forms.append(
                _Form(
                    PUT_NAME_DOWN,
                    {JOB: (_one_of(pairs), None)},
                    lambda reply: ClaimTask(task_id=pairs[reply[JOB]]),
                )
            )
        elif self.together and self.partners:
            pairs = {job_number(task): task for task in self.together}
            forms.append(
                _Form(
                    TAKE_FOR_TWO,
                    {JOB: (_one_of(pairs), None), WITH: (_one_of(self.partners), None)},
                    lambda reply: ClaimTask(task_id=pairs[reply[JOB]], partner=reply[WITH]),
                )
            )
        return forms


class _Working(_Allowance):
    """Work on the job `task_id` the resident holds, whose `parts` are not yet in; the part is
    asked for only when it is not simply the job's one part."""

    task_id: str
    parts: tuple[PartNumber, ...] = Field(min_length=1)

    def _part(self) -> Fields:
        return {} if self.parts == (1,) else {PART: (_one_of(self.parts), None)}


class MayCheck(_Working):
    """Trying one's code for a part of one's job against the client's examples."""

    kind: Literal[ActionKind.CHECK_WORK] = ActionKind.CHECK_WORK

    def forms(self) -> list[_Form]:
        def check(reply: Mapping[str, Any]) -> Action:
            return CheckWork(task_id=self.task_id, part=reply.get(PART, 1), solution=reply[CODE])

        return [_Form(TRY, {**self._part(), CODE: (str, None)}, check)]


class MaySubmit(_Working):
    """Handing in a part of one's job, as finished or as unfinished."""

    kind: Literal[ActionKind.SUBMIT_WORK] = ActionKind.SUBMIT_WORK

    def forms(self) -> list[_Form]:
        declared = {word: declaration for declaration, word in DECLARED.items()}
        fields: Fields = {
            **self._part(),
            CODE: (str, None),
            AS: (_one_of(declared), None),
            TELLING: (str, None),
        }

        def submit(reply: Mapping[str, Any]) -> Action:
            return SubmitWork(
                task_id=self.task_id,
                part=reply.get(PART, 1),
                solution=reply[CODE],
                declaration=declared[reply[AS]],
                report=reply[TELLING],
            )

        return [_Form(HAND_IN, fields, submit)]


class MayGive(_Allowance):
    """Handing money to one of the people present; the amount is written under `units`, the
    town's word for its money counted (`dollars`, `crowns`)."""

    kind: Literal[ActionKind.GIVE] = ActionKind.GIVE
    to: tuple[str, ...] = Field(min_length=1)
    units: str = Field(min_length=1)

    def forms(self) -> list[_Form]:
        fields: Fields = {
            TO: (_one_of(self.to), None),
            self.units: (Annotated[int, Field(ge=1)], None),
            NOTE: (str, None),
        }

        def give(reply: Mapping[str, Any]) -> Action:
            return Give(to=reply[TO], amount=reply[self.units], note=reply[NOTE])

        return [_Form(HAND_OVER, fields, give)]


class MayRate(_Allowance):
    """Marking, in the clerk's ledger, the people one spent time with today."""

    kind: Literal[ActionKind.RATE_PEERS] = ActionKind.RATE_PEERS
    whom: tuple[str, ...] = Field(min_length=1)

    def forms(self) -> list[_Form]:
        mark = create_model(
            "Mark",
            __base__=StrictModel,
            who=(_one_of(self.whom), ...),
            mark=(Literal[1, 2, 3, 4, 5], ...),
            because=(str, ...),
        )

        def rate(reply: Mapping[str, Any]) -> Action:
            marks = (
                PeerRating(target=m[WHO], score=m[MARK_GIVEN], reason=m[BECAUSE])
                for m in reply[MARKS]
            )
            return RatePeers(ratings=tuple(marks))

        return [_Form(MARK, {MARKS: (list[mark], None)}, rate)]


class MayVote(_Allowance):
    """Giving the clerk one's answer to the question put to a meeting, one of `options`."""

    kind: Literal[ActionKind.VOTE] = ActionKind.VOTE
    options: tuple[str, ...] = Field(min_length=2)

    def forms(self) -> list[_Form]:
        fields: Fields = {REPLY_GIVEN: (_one_of(self.options), None)}
        return [_Form(GIVE_ANSWER, fields, lambda reply: Vote(choice=reply[REPLY_GIVEN]))]


Allowance = Annotated[
    MayPlan
    | MaySpeak
    | MayLeave
    | MayPass
    | MayClaim
    | MayCheck
    | MaySubmit
    | MayGive
    | MayRate
    | MayVote,
    Field(discriminator="kind"),
]
"""What a resident can do of one kind at a moment, with the values that are really possible."""

ALLOWANCES: dict[ActionKind, type[_Allowance]] = {
    allowance.model_fields["kind"].default: allowance
    for allowance in get_args(get_args(Allowance)[0])
}


class Card:
    """The forms of a reply at a moment whose `allowed` they come from.

    `model` is the reply model: its JSON schema is what a server enforces, and `form(model)`
    is the card the resident reads. `decision` translates a validated reply into the Decision
    it means. Raises ValueError if nothing is allowed or two forms would read the same.
    """

    def __init__(self, allowed: Sequence[Allowance]) -> None:
        self._forms = [form for allowance in allowed for form in allowance.forms()]
        if not self._forms:
            raise ValueError("a card needs at least one form")
        if len({form.does for form in self._forms}) != len(self._forms):
            raise ValueError("two forms of a card would read the same")
        self._models = [_model(index, form) for index, form in enumerate(self._forms)]
        self.model: type[BaseModel] = (
            self._models[0] if len(self._models) == 1 else RootModel[Union[tuple(self._models)]]  # noqa: UP007
        )

    def decision(self, reply: BaseModel) -> Decision:
        answer = reply.root if isinstance(reply, RootModel) else reply
        values = answer.model_dump(by_alias=True)
        form = self._forms[self._models.index(type(answer))]
        return Decision(thought=values[THOUGHT], action=form.action(values))


def form(model: type[BaseModel]) -> str:
    """How a reply to `model` is written, as the resident reads it: one line for each form
    the model's JSON schema allows, then, named by capital letters, any described object
    nested in them, with its description."""
    schema = model.model_json_schema()
    defs, notes = schema.get("$defs", {}), []
    lines = [_shape(option, defs, notes, top=True) for option in schema.get("anyOf", [schema])]
    return "\n".join([ANSWERS if len(lines) > 1 else ANSWER, *lines, *notes])


def correction(model: type[BaseModel], error: ValidationError) -> str:
    """What a resident is told when its answer could not be read as a reply to `model`: what
    was wrong, by the keys it writes and in the card's plain words (a choice not shown, a
    missing key, a key that is not part of the form, or the rule of a nightly reply it
    broke), or that the answer as a whole could not be read; then to answer again. The
    choices themselves are not repeated, so that the correction cannot lean towards one."""
    keys = _keys(model.model_json_schema())
    problems = []
    for problem in _closest(error.errors(), keys):
        if problem["type"] == "value_error":
            problems.append(str(problem["ctx"]["error"]))
            continue
        key = next((part for part in reversed(problem["loc"]) if part in keys), None)
        if key is None:
            return UNREADABLE
        problems.append(_PROBLEMS.get(problem["type"], NOT_AS_SHOWN).format(key=key))
    return UNREAD.format(problems="; ".join(dict.fromkeys(problems)))


_PROBLEMS = {
    "missing": MISSING,
    "extra_forbidden": NOT_IN_FORM,
    "literal_error": NOT_A_CHOICE,
    "enum": NOT_A_CHOICE,
}
"""How each kind of validation problem with a key is told; any other is NOT_AS_SHOWN."""


def _keys(schema: Any) -> set[str]:
    """Every key an object of `schema`, or nested in it, can have."""
    if isinstance(schema, list):
        return {key for item in schema for key in _keys(item)}
    if not isinstance(schema, dict):
        return set()
    own = set(schema["properties"]) if isinstance(schema.get("properties"), dict) else set()
    return own | {key for value in schema.values() for key in _keys(value)}


def _closest(problems: list[Any], keys: set[str]) -> list[Any]:
    """The problems of an answer that fits no member of a union, which validation reports for
    every member under the member's name, kept for the members it came closest to: those
    with the fewest problems, and of those the fewest values that are not a choice (an answer
    to one form that holds a key too many is closer to it than to a form it names wrongly)."""
    members: dict[tuple[Any, ...], list[Any]] = {}
    kept = []
    for problem in problems:
        loc = problem["loc"]
        at = next(
            (i for i, part in enumerate(loc) if isinstance(part, str) and part not in keys), None
        )
        if at is None:
            kept.append(problem)
        else:
            members.setdefault(loc[: at + 1], []).append(problem)

    def distance(found: list[Any]) -> tuple[int, int]:
        return len(found), sum(problem["type"] == "literal_error" for problem in found)

    nearest: dict[tuple[Any, ...], tuple[int, int]] = {}
    for member, found in members.items():
        union = member[:-1]
        nearest[union] = min(nearest.get(union, distance(found)), distance(found))
    closest = (
        found for member, found in members.items() if distance(found) == nearest[member[:-1]]
    )
    return kept + [problem for found in closest for problem in found]


def _one_of(values: Iterable[Any]) -> Any:
    """The type of a choice among `values`, in sorted order: a card is the same whatever order
    the moment listed them in (and `typing`, which caches a union by its equal members in any
    order, cannot hand back another moment's order)."""
    return Literal[tuple(sorted(values))]


def _model(index: int, form: _Form) -> type[BaseModel]:
    fields: dict[str, Any] = {THOUGHT: (str, ...), DOES: (Literal[form.does], ...)}
    for position, (key, (annotation, word)) in enumerate(form.fields.items()):
        fields[f"field_{position}"] = (annotation, Field(alias=key, description=word))
    return create_model(f"Form{index}", __base__=StrictModel, **fields)


def _shape(node: dict[str, Any], defs: dict[str, Any], notes: list[str], top: bool = False) -> str:
    """`node` of a JSON schema as a template; a described object other than a top-level form
    is named by the next letter and noted in `notes`."""
    if "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[1]]
    if node.get("type") == "object":
        word = ""
    else:
        word = f" {node['description']}" if "description" in node else ""
    if node.get("type") == "object" and "description" in node and not top:
        index = len(notes)
        notes.append("")
        shape = _shape(node, defs, notes, top=True)
        description = " ".join(node["description"].split())
        name = string.ascii_uppercase[index]
        notes[index] = NOTED.format(name=name, shape=shape, description=description)
        return name
    return _alternatives(_values(node, defs, notes)) + word


def _values(node: dict[str, Any], defs: dict[str, Any], notes: list[str]) -> list[str]:
    """The alternatives `node` allows, each as a template."""
    if "$ref" in node:
        return [_shape(node, defs, notes)]
    if "const" in node:
        return [json.dumps(node["const"], ensure_ascii=False)]
    if "enum" in node:
        return [json.dumps(value, ensure_ascii=False) for value in node["enum"]]
    if "anyOf" in node:
        return [value for option in node["anyOf"] for value in _values(option, defs, notes)]
    match node.get("type"):
        case "object" if "properties" in node:
            pairs = (
                f"{json.dumps(key, ensure_ascii=False)}: {_shape(value, defs, notes)}"
                for key, value in node["properties"].items()
            )
            return ["{" + ", ".join(pairs) + "}"]
        case "object":
            return ["{" + f"{TEXT}: {_shape(node['additionalProperties'], defs, notes)}" + "}"]
        case "array":
            return [f"[{_shape(node['items'], defs, notes)}, {MORE}]"]
        case "string":
            return [TEXT]
        case "integer" | "number":
            return [NUMBER]
        case "boolean":
            return [TRUTH]
        case "null":
            return [NOTHING]
    raise ValueError(f"no template for the schema {node}")


def _alternatives(values: Sequence[str]) -> str:
    """`a`, `a or b`, `a, b or c`."""
    return " or ".join([", ".join(values[:-1]), values[-1]] if len(values) > 1 else values)
