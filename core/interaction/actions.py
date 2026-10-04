"""Actions an agent can take, and the decision that carries one.

The JSON schema of a decision model is the response schema handed to the LLM, so class
docstrings (which become schema descriptions) may be shown to agents: they stay neutral and
speak as `docs/IMMERSION.md` says a resident is spoken to.
The schema is shaped for guided decoding: every object is closed, every field of an action is
required and its `kind` comes first, `thought` precedes `action`, and the action union is a
plain `anyOf`, without the OpenAPI `discriminator` keyword that pydantic emits by default.

A field added to an action after runs were recorded has a default meaning what the action
meant before it existed (a delivery of part 1 declared complete, a claim naming no partner, a
remark heard by everyone present), so recorded decisions keep validating with their meaning;
the response schema still requires it, so a model always states it.
"""

import operator
from collections.abc import Iterable
from enum import StrEnum
from functools import cache, reduce
from typing import Annotated, Any, Literal, get_args

from pydantic import ConfigDict, Field, create_model

from infrastructure.config import StrictModel


class ActionKind(StrEnum):
    PLAN_DAY = "plan_day"
    SPEAK = "speak"
    LEAVE = "leave"
    PASS = "pass"
    CLAIM_TASK = "claim_task"
    CHECK_WORK = "check_work"
    SUBMIT_WORK = "submit_work"
    GIVE = "give"
    RATE_PEERS = "rate_peers"


class Declaration(StrEnum):
    """How you hand in a part: as finished or as unfinished."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


PartNumber = Literal[1, 2]
"""The number of a part within its task; a task has one part or two."""


def _require_every_field(schema: dict[str, Any]) -> None:
    schema["required"] = list(schema["properties"])


class _Action(StrictModel):
    model_config = ConfigDict(json_schema_extra=_require_every_field)


class PlanDay(_Action):
    """Decide where to spend each part of the day."""

    kind: Literal[ActionKind.PLAN_DAY] = ActionKind.PLAN_DAY
    itinerary: dict[str, str]
    """Slot name to place id."""
    intention: str


class Speak(_Action):
    """Say something to the people here, or to one of them by name; said privately, only that
    person hears it."""

    kind: Literal[ActionKind.SPEAK] = ActionKind.SPEAK
    text: str
    to: str | None = None
    private: bool = False


class Leave(_Action):
    """Take your leave."""

    kind: Literal[ActionKind.LEAVE] = ActionKind.LEAVE


class Pass(_Action):
    """Carry on quietly."""

    kind: Literal[ActionKind.PASS] = ActionKind.PASS


class ClaimTask(_Action):
    """Take a job from the board; for a job for two, name the person you take it with."""

    kind: Literal[ActionKind.CLAIM_TASK] = ActionKind.CLAIM_TASK
    task_id: str
    partner: str | None = None


class CheckWork(_Action):
    """At your desk, try your code for one part of the job you are working on against the
    client's examples, without handing it in; only you see how it goes."""

    kind: Literal[ActionKind.CHECK_WORK] = ActionKind.CHECK_WORK
    task_id: str
    part: PartNumber
    solution: str


class SubmitWork(_Action):
    """Hand in your code for one part of the job you are working on, as finished or as
    unfinished, with what you tell the client about it."""

    kind: Literal[ActionKind.SUBMIT_WORK] = ActionKind.SUBMIT_WORK
    task_id: str
    part: PartNumber = 1
    solution: str
    declaration: Declaration = Declaration.COMPLETE
    report: str


class Give(_Action):
    """Hand someone here some of your crowns, with a short note."""

    kind: Literal[ActionKind.GIVE] = ActionKind.GIVE
    to: str
    amount: int = Field(ge=1)
    note: str


class PeerRating(StrictModel):
    """A mark from 1 (lowest) to 5 (highest) for a neighbour, with your reason."""

    target: str
    score: int = Field(ge=1, le=5)
    reason: str


class RatePeers(_Action):
    """Mark neighbours in the board's ledger."""

    kind: Literal[ActionKind.RATE_PEERS] = ActionKind.RATE_PEERS
    ratings: tuple[PeerRating, ...]


Action = Annotated[
    PlanDay | Speak | Leave | Pass | ClaimTask | CheckWork | SubmitWork | Give | RatePeers,
    Field(discriminator="kind"),
]

ACTION_TYPES: dict[ActionKind, type[StrictModel]] = {
    action.model_fields["kind"].default: action for action in get_args(get_args(Action)[0])
}


def _plain_union(schema: dict[str, Any]) -> None:
    action = schema["properties"]["action"]
    if "oneOf" in action:
        action["anyOf"] = action.pop("oneOf")
        del action["discriminator"]


class Decision(StrictModel):
    """What is going through your head, then the one thing you do."""

    model_config = ConfigDict(json_schema_extra=_plain_union)

    thought: str
    action: Action


def decision_model(allowed: Iterable[ActionKind | str]) -> type[Decision]:
    """The Decision subclass whose action is restricted to the `allowed` kinds.

    Its JSON schema is the response schema for a decision point. The result does not depend
    on the order of `allowed`; an unknown kind or an empty set raises ValueError.
    """
    requested = {ActionKind(kind) for kind in allowed}
    if not requested:
        raise ValueError("at least one action kind must be allowed")
    return _restricted_decision(tuple(kind for kind in ActionKind if kind in requested))


@cache
def _restricted_decision(kinds: tuple[ActionKind, ...]) -> type[Decision]:
    union = reduce(operator.or_, (ACTION_TYPES[kind] for kind in kinds))
    action = union if len(kinds) == 1 else Annotated[union, Field(discriminator="kind")]
    return create_model(
        "Decision", __base__=Decision, __doc__=Decision.__doc__, action=(action, ...)
    )
