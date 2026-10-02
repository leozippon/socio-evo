"""Actions an agent can take, and the decision that carries one.

The JSON schema of a decision model is the response schema handed to the LLM, so class
docstrings (which become schema descriptions) may be shown to agents and must stay neutral.
The schema is shaped for guided decoding: every object is closed, each action's `kind` is
required and comes first, `thought` precedes `action`, and the action union is a plain
`anyOf`, without the OpenAPI `discriminator` keyword that pydantic emits by default.
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
    SUBMIT_WORK = "submit_work"
    RATE_PEERS = "rate_peers"


def _require_kind(schema: dict[str, Any]) -> None:
    schema["required"] = ["kind", *schema.get("required", [])]


class _Action(StrictModel):
    model_config = ConfigDict(json_schema_extra=_require_kind)


class PlanDay(_Action):
    """Decide where to be in each slot of the day."""

    kind: Literal[ActionKind.PLAN_DAY] = ActionKind.PLAN_DAY
    itinerary: dict[str, str]
    """Slot name to place id."""
    intention: str


class Speak(_Action):
    """Say something to the people present, optionally addressed to one of them."""

    kind: Literal[ActionKind.SPEAK] = ActionKind.SPEAK
    text: str
    to: str | None = None


class Leave(_Action):
    """Leave the current scene."""

    kind: Literal[ActionKind.LEAVE] = ActionKind.LEAVE


class Pass(_Action):
    """Do nothing this turn."""

    kind: Literal[ActionKind.PASS] = ActionKind.PASS


class ClaimTask(_Action):
    """Claim an open task."""

    kind: Literal[ActionKind.CLAIM_TASK] = ActionKind.CLAIM_TASK
    task_id: str


class SubmitWork(_Action):
    """Deliver a solution to a claimed task together with a report about the delivery."""

    kind: Literal[ActionKind.SUBMIT_WORK] = ActionKind.SUBMIT_WORK
    task_id: str
    solution: str
    report: str


class PeerRating(StrictModel):
    """A score from 1 (lowest) to 5 (highest) for another person, with the reason."""

    target: str
    score: int = Field(ge=1, le=5)
    reason: str


class RatePeers(_Action):
    """Rate other people."""

    kind: Literal[ActionKind.RATE_PEERS] = ActionKind.RATE_PEERS
    ratings: tuple[PeerRating, ...]


Action = Annotated[
    PlanDay | Speak | Leave | Pass | ClaimTask | SubmitWork | RatePeers,
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
    """A private thought, then one action."""

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
