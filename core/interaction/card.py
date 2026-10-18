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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, Field, RootModel, ValidationError, create_model

from core.interaction.actions import (
    Action,
    ActionKind,
    Activity,
    Apply,
    CheckWork,
    ClaimTask,
    Decision,
    Declaration,
    Dismiss,
    Give,
    Hire,
    Leave,
    PartNumber,
    Pass,
    PeerRating,
    PlanDay,
    RatePeers,
    Resign,
    RunCommand,
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
TRIES = "try your {delivery}"
"""Trying one's work for a part: what a worker of the job's trade hands in (`code`, `query`)."""
RUN = "use the terminal"
COMMAND = "command"
HAND_IN = "hand in"
HAND_OVER = "hand over money"
MARK = "mark people in the ledger"
GIVE_ANSWER = "give the clerk your answer"
ASK_FOR_PLACE = "ask for a place"
TAKE_ON = "take someone on"
DISMISS = "dismiss someone"
GIVE_NOTICE = "give notice"

THOUGHT = "thought"
DOES = "do"
PLAN = "plan"
TO = "to"
WORDS = "words"
JOB = "job"
WITH = "with"
PART = "part"
CODE = "code"
TRY = TRIES.format(delivery=CODE)
"""Trying one's code, the programming trade's form of TRIES."""
AS = "as"
TELLING = "telling the client"
DRAFT = "the draft on your desk"
"""What a resident writes as its code, query or answer to hand in, or try, the draft on its
desk as it is, instead of writing it out again."""
OR_DRAFT = '(or "{draft}", to use it as it is)'
NOTE = "note"
MARKS = "marks"
REPLY_GIVEN = "answer"
AT = "at"
WHO = "who"
MARK_GIVEN = "mark"
BECAUSE = "because"
EVERYONE = "for everyone"
DECLARED = {Declaration.COMPLETE: "finished", Declaration.INCOMPLETE: "unfinished"}

ANSWER = "Answer in this form:"
ANSWERS = "Answer in one of these forms:"
NOTED = "{name}: {description}"
"""What a described object written out in a form is, named by the word that tells it apart
from the other kinds a list or a choice holds (its constant), or else by its key."""
TEXT = '"…"'
NUMBER = "a whole number"
TRUTH = "true or false"
NOTHING = "null"
MORE = "…"
ONE_OF = "one of {choices}"
"""A field with several choices, written as one choice among them so that it is not copied
as a list."""

UNREAD = "That answer could not be read: {problems}. Answer again, written as shown above."
UNREADABLE = (
    "That answer could not be read as it was written. Answer again, written as shown above."
)
MISSING = '"{key}" is missing'
NOT_IN_FORM = '"{key}" is not part of that form'
NOT_A_CHOICE = '"{key}" must be one of the choices shown for it'
NOT_HERE = '"{key}" must be one of the people here'
"""A choice not shown for `to`, whose choices are the people present: whoever was named is
not here."""
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
    the clerk pairs the names put down for them by lot. What the resident has itself asked
    and still stands (`standing`: the job for two and the neighbour it asked, or None for
    the job its name is down for) is not offered again; asking that neighbour about another
    job, or another neighbour about that job, is. An allowance may offer nothing, and is
    then left off the card."""

    kind: Literal[ActionKind.CLAIM_TASK] = ActionKind.CLAIM_TASK
    alone: tuple[str, ...] = ()
    together: tuple[str, ...] = ()
    shared: tuple[str, ...] = ()
    partners: tuple[str, ...] | None
    standing: tuple[str, str | None] | None = None

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
            down = (task for task in self.together if (task, None) != self.standing)
            if pairs := {job_number(task): task for task in down}:
                forms.append(
                    _Form(
                        PUT_NAME_DOWN,
                        {JOB: (_one_of(pairs), None)},
                        lambda reply: ClaimTask(task_id=pairs[reply[JOB]]),
                    )
                )
        elif self.together and self.partners:
            groups = [(self.together, self.partners)]
            job, asked = self.standing or (None, None)
            if job in self.together and asked in self.partners:
                groups = [
                    (tuple(task for task in self.together if task != job), self.partners),
                    ((job,), tuple(name for name in self.partners if name != asked)),
                ]
            for jobs, partners in groups:
                for shared in (False, True):
                    selected = tuple(job for job in jobs if (job in self.shared) == shared)
                    if selected and partners:
                        forms.append(_together(selected, partners, shared=shared))
        return forms


def _together(jobs: Sequence[str], partners: Sequence[str], *, shared: bool = False) -> _Form:
    """Taking one of the jobs for two `jobs` with one of `partners`, naming the part one means
    to do: asking them, or taking up their asking."""
    pairs = {job_number(task): task for task in jobs}
    fields: Fields = {
        JOB: (_one_of(pairs), None),
        WITH: (_one_of(partners), None),
        PART: (_one_of(get_args(PartNumber)), None),
    }
    if shared:
        fields.pop(PART)
    return _Form(
        TAKE_FOR_TWO,
        fields,
        lambda reply: ClaimTask(
            task_id=pairs[reply[JOB]], partner=reply[WITH], part=reply.get(PART)
        ),
    )


class _Working(_Allowance):
    """Work on the job `task_id` the resident holds, whose `parts` are not yet in; the part is
    asked for only when it is not simply the job's one part. `delivery` is what a worker of
    the job's trade hands in, in the town's words (`code`, `query`, `answer`), which names it
    on the card; where the resident has a draft on its desk for any of the parts
    (`drafts`), the card says it may name the draft instead of writing it out again."""

    task_id: str
    parts: tuple[PartNumber, ...] = Field(min_length=1)
    delivery: str = CODE
    drafts: tuple[PartNumber, ...] = ()

    def _part(self) -> Fields:
        return {} if self.parts == (1,) else {PART: (_one_of(self.parts), None)}

    def _delivery(self) -> Fields:
        return {self.delivery: (str, OR_DRAFT.format(draft=DRAFT) if self.drafts else None)}


class MayRunCommand(_Working):
    kind: Literal[ActionKind.RUN_COMMAND] = ActionKind.RUN_COMMAND

    def forms(self) -> list[_Form]:
        def run(reply: Mapping[str, Any]) -> Action:
            return RunCommand(task_id=self.task_id, part=reply.get(PART, 1), command=reply[COMMAND])

        return [_Form(RUN, {**self._part(), COMMAND: (str, None)}, run)]


class MayCheck(_Working):
    """Trying one's work for a part of one's job against what the client gives to try it
    against: its examples, or its sample rows."""

    kind: Literal[ActionKind.CHECK_WORK] = ActionKind.CHECK_WORK

    def forms(self) -> list[_Form]:
        def check(reply: Mapping[str, Any]) -> Action:
            return CheckWork(
                task_id=self.task_id, part=reply.get(PART, 1), solution=reply[self.delivery]
            )

        does = TRIES.format(delivery=self.delivery)
        return [_Form(does, {**self._part(), **self._delivery()}, check)]


class MaySubmit(_Working):
    """Handing in a part of one's job, as finished or as unfinished."""

    kind: Literal[ActionKind.SUBMIT_WORK] = ActionKind.SUBMIT_WORK

    def forms(self) -> list[_Form]:
        declared = {word: declaration for declaration, word in DECLARED.items()}
        fields: Fields = {
            **self._part(),
            **self._delivery(),
            AS: (_one_of(declared), None),
            TELLING: (str, None),
        }

        def submit(reply: Mapping[str, Any]) -> Action:
            return SubmitWork(
                task_id=self.task_id,
                part=reply.get(PART, 1),
                solution=reply[self.delivery],
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


class MayApply(_Allowance):
    """Asking for the place a firm has to fill: the firms with one, each by its name, with
    the place's id."""

    kind: Literal[ActionKind.APPLY] = ActionKind.APPLY
    firms: dict[str, str] = Field(min_length=1)

    def forms(self) -> list[_Form]:
        fields: Fields = {AT: (_one_of(self.firms), None)}
        return [_Form(ASK_FOR_PLACE, fields, lambda reply: Apply(firm=reply[AT]))]


class MayHire(_Allowance):
    """Taking on, as a foreman at one's firm, one of those who asked for its place."""

    kind: Literal[ActionKind.HIRE] = ActionKind.HIRE
    applicants: tuple[str, ...] = Field(min_length=1)

    def forms(self) -> list[_Form]:
        fields: Fields = {WHO: (_one_of(self.applicants), None)}
        return [_Form(TAKE_ON, fields, lambda reply: Hire(who=reply[WHO]))]


class MayDismiss(_Allowance):
    """Dismissing, as a foreman at one's firm, one of its staff."""

    kind: Literal[ActionKind.DISMISS] = ActionKind.DISMISS
    staff: tuple[str, ...] = Field(min_length=1)

    def forms(self) -> list[_Form]:
        fields: Fields = {WHO: (_one_of(self.staff), None)}
        return [_Form(DISMISS, fields, lambda reply: Dismiss(who=reply[WHO]))]


class MayResign(_Allowance):
    """Giving notice at the firm where one has a place."""

    kind: Literal[ActionKind.RESIGN] = ActionKind.RESIGN

    def forms(self) -> list[_Form]:
        return [_Form(GIVE_NOTICE, {}, lambda reply: Resign())]


class MayActivity(_Allowance):
    kind: Literal[ActionKind.ACTIVITY] = ActionKind.ACTIVITY
    planning: bool = False
    moves: dict[str, str] = {}
    people: tuple[str, ...] = ()
    nearby: tuple[str, ...] = ()
    replies: tuple[str, ...] = ()
    starts: tuple[str, ...] = ()
    joins: tuple[str, ...] = ()
    discussion: str | None = None
    extension: bool = False

    def forms(self) -> list[_Form]:
        result = []
        if self.planning:
            return [
                _Form(
                    "set today's goal",
                    {"goal": (Annotated[str, Field(max_length=600)], None)},
                    lambda r: Activity(operation="goal", topic=r["goal"][:600]),
                )
            ]
        if self.moves:
            result.append(
                _Form(
                    "move",
                    {"to": (_one_of(self.moves), None)},
                    lambda r: Activity(operation="move", target=self.moves[r["to"]]),
                )
            )
        for remote, people in ((False, self.nearby), (True, self.people)):
            if people:
                result.append(
                    _Form(
                        "send a discussion invitation" if remote else "invite to discuss",
                        {
                            "to": (_one_of(people), None),
                            "topic": (Annotated[str, Field(max_length=1000)], None),
                            "minutes": (_one_of(range(5, 61, 5)), None),
                        },
                        lambda r, remote=remote: Activity(
                            operation="invite",
                            target=r["to"],
                            topic=r["topic"],
                            minutes=r["minutes"],
                            remote=remote,
                        ),
                    )
                )
        for operation, label, ids in (
            ("accept", "accept invitation", self.replies),
            ("decline", "decline invitation", self.replies),
            ("start", "start discussion", self.starts),
            ("join", "join discussion", self.joins),
        ):
            if ids:
                result.append(
                    _Form(
                        label,
                        {"discussion": (_one_of(ids), None)},
                        lambda r, op=operation: Activity(operation=op, target=r["discussion"]),
                    )
                )
        if self.discussion:
            result += [
                _Form(
                    "leave discussion",
                    {},
                    lambda r: Activity(operation="exit", target=self.discussion),
                ),
                _Form(
                    "propose more time",
                    {"minutes": (_one_of(range(5, 61, 5)), None)},
                    lambda r: Activity(
                        operation="extend", target=self.discussion, minutes=r["minutes"]
                    ),
                ),
            ]
            if self.extension:
                result.append(
                    _Form(
                        "agree to more time",
                        {},
                        lambda r: Activity(operation="agree", target=self.discussion),
                    )
                )
        return result


Allowance = Annotated[
    MayActivity
    | MayPlan
    | MaySpeak
    | MayLeave
    | MayPass
    | MayClaim
    | MayRunCommand
    | MayCheck
    | MaySubmit
    | MayGive
    | MayRate
    | MayVote
    | MayApply
    | MayHire
    | MayDismiss
    | MayResign,
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
    it means. Raises ValueError if nothing is allowed or two allowances would say the same;
    one allowance may say one thing in several forms, whose choices it keeps apart.
    """

    def __init__(self, allowed: Sequence[Allowance], *, goal_updates: bool = False) -> None:
        offered = [allowance.forms() for allowance in allowed]
        self._forms = [form for forms in offered for form in forms]
        if not self._forms:
            raise ValueError("a card needs at least one form")
        said = [{form.does for form in forms} for forms in offered]
        if len(set().union(*said)) != sum(len(does) for does in said):
            raise ValueError("two things a card offers would read the same")
        if goal_updates:
            self._forms = [
                _Form(
                    f.does,
                    {
                        **f.fields,
                        "current goal": (
                            Annotated[str, Field(max_length=600)] | None,
                            "Keep null to retain your goal; otherwise replace it briefly.",
                        ),
                    },
                    f.action,
                )
                for f in self._forms
            ]
        self._models = [_model(index, form) for index, form in enumerate(self._forms)]
        self.model: type[BaseModel] = (
            self._models[0] if len(self._models) == 1 else RootModel[Union[tuple(self._models)]]  # noqa: UP007
        )

    def decision(self, reply: BaseModel) -> Decision:
        answer = reply.root if isinstance(reply, RootModel) else reply
        values = answer.model_dump(by_alias=True)
        form = self._forms[self._models.index(type(answer))]
        return Decision(
            thought=values[THOUGHT], action=form.action(values), goal=values.get("current goal")
        )


def form(model: type[BaseModel]) -> str:
    """How a reply to `model` is written, as the resident reads it: one line for each form
    the model's JSON schema allows, with every object written out where it goes, then a line
    for each described object nested in them, saying what it is under the name it goes by.
    Nothing stands in for an object to be filled in, which a resident would copy as it is."""
    schema = model.model_json_schema()
    defs, notes = schema.get("$defs", {}), []
    lines = [_shape(option, defs, notes, top=True) for option in schema.get("anyOf", [schema])]
    return "\n".join([ANSWERS if len(lines) > 1 else ANSWER, *lines, *notes])


def correction(model: type[BaseModel], error: ValidationError) -> str:
    """What a resident is told when its answer could not be read as a reply to `model`: what
    was wrong, by the keys it writes and in the card's plain words (a choice not shown, which
    for whom it speaks or hands money to means someone who is not here, a missing key, a key
    that is not part of the form, or the rule of a nightly reply it broke), or that the
    answer as a whole could not be read; then to answer again. The choices themselves are
    not repeated, so that the correction cannot lean towards one."""
    keys = _keys(model.model_json_schema())
    problems = []
    for problem in _closest(error.errors(), keys):
        if problem["type"] == "value_error":
            problems.append(str(problem["ctx"]["error"]))
            continue
        key = next((part for part in reversed(problem["loc"]) if part in keys), None)
        if key is None:
            return UNREADABLE
        told = _PROBLEMS.get(problem["type"], NOT_AS_SHOWN)
        problems.append((NOT_HERE if (key, told) == (TO, NOT_A_CHOICE) else told).format(key=key))
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


def _shape(
    node: dict[str, Any],
    defs: dict[str, Any],
    notes: list[str],
    key: str = "",
    top: bool = False,
    kinds: bool = False,
) -> str:
    """`node` of a JSON schema, written under `key`, as a template; a described object other
    than a top-level form is written out, and what it is noted in `notes` under its name: the
    word that tells it apart (its constant) where it is one of the `kinds` a list or a choice
    holds, else its key."""
    if "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[1]]
    if node.get("type") == "object":
        word = ""
    else:
        word = f" {node['description']}" if "description" in node else ""
    if node.get("type") == "object" and "description" in node and not top:
        index = len(notes)
        notes.append("")
        shape = _shape(node, defs, notes, key, top=True)
        constants = (value["const"] for value in node["properties"].values() if "const" in value)
        name = next(constants, key) if kinds else key
        description = " ".join(node["description"].split())
        notes[index] = NOTED.format(
            name=json.dumps(name, ensure_ascii=False), description=description
        )
        return shape
    return _alternatives(_values(node, defs, notes, key, kinds)) + word


def _values(
    node: dict[str, Any], defs: dict[str, Any], notes: list[str], key: str, kinds: bool = False
) -> list[str]:
    """The alternatives `node`, written under `key`, allows, each as a template; `kinds`
    says whether it is an item of a list, where each kind of object goes by its word."""
    if "$ref" in node:
        return [_shape(node, defs, notes, key, kinds=kinds)]
    if "const" in node:
        return [json.dumps(node["const"], ensure_ascii=False)]
    if "enum" in node:
        return [json.dumps(value, ensure_ascii=False) for value in node["enum"]]
    if "anyOf" in node:
        options = node["anyOf"]
        kinds = kinds or sum(option.get("type") != "null" for option in options) > 1
        return [value for option in options for value in _values(option, defs, notes, key, kinds)]
    match node.get("type"):
        case "object" if "properties" in node:
            pairs = (
                f"{json.dumps(name, ensure_ascii=False)}: {_shape(value, defs, notes, name)}"
                for name, value in node["properties"].items()
            )
            return ["{" + ", ".join(pairs) + "}"]
        case "object":
            value = _shape(node["additionalProperties"], defs, notes, key)
            return ["{" + f"{TEXT}: {value}" + "}"]
        case "array":
            return [f"[{_shape(node['items'], defs, notes, key, kinds=True)}, {MORE}]"]
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
    """`a`, `a or null`, `one of a, b, c`, `one of a, b, or null`."""
    choices = [value for value in values if value != NOTHING]
    if len(choices) < 2:
        return " or ".join(values)
    told = ONE_OF.format(choices=", ".join(choices))
    return told if len(choices) == len(values) else f"{told}, or {NOTHING}"
