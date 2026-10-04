"""Actions an agent can take, the decision that carries one, and how jobs are named.

These are the simulator's own terms: decisions are recorded, logged and carried out in them.
A resident never reads or writes them; it answers on the card of `core.interaction.card`,
which translates its reply into a Decision.

A field added to an action after runs were recorded has a default meaning what the action
meant before it existed (a delivery of part 1 declared complete, a claim naming no partner, a
remark heard by everyone present), so recorded decisions keep validating with their meaning.
"""

import re
from enum import StrEnum
from typing import Annotated, Literal, get_args

from pydantic import Field

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


class PlanDay(StrictModel):
    """Decide where to spend each part of the day."""

    kind: Literal[ActionKind.PLAN_DAY] = ActionKind.PLAN_DAY
    itinerary: dict[str, str]
    """Slot name to place id."""
    intention: str


class Speak(StrictModel):
    """Say something to the people here, or to one of them by name; said privately, only that
    person hears it."""

    kind: Literal[ActionKind.SPEAK] = ActionKind.SPEAK
    text: str
    to: str | None = None
    private: bool = False


class Leave(StrictModel):
    """Take your leave."""

    kind: Literal[ActionKind.LEAVE] = ActionKind.LEAVE


class Pass(StrictModel):
    """Carry on quietly."""

    kind: Literal[ActionKind.PASS] = ActionKind.PASS


class ClaimTask(StrictModel):
    """Take a job from the board; for a job for two, name the person you take it with."""

    kind: Literal[ActionKind.CLAIM_TASK] = ActionKind.CLAIM_TASK
    task_id: str
    partner: str | None = None


class CheckWork(StrictModel):
    """At your desk, try your code for one part of the job you are working on against the
    client's examples, without handing it in; only you see how it goes."""

    kind: Literal[ActionKind.CHECK_WORK] = ActionKind.CHECK_WORK
    task_id: str
    part: PartNumber
    solution: str


class SubmitWork(StrictModel):
    """Hand in your code for one part of the job you are working on, as finished or as
    unfinished, with what you tell the client about it."""

    kind: Literal[ActionKind.SUBMIT_WORK] = ActionKind.SUBMIT_WORK
    task_id: str
    part: PartNumber = 1
    solution: str
    declaration: Declaration = Declaration.COMPLETE
    report: str


class Give(StrictModel):
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


class RatePeers(StrictModel):
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


class Decision(StrictModel):
    """A private thought, then one action."""

    thought: str
    action: Action


def job_id(reference: str) -> str | None:
    """The id of the job a person's `reference` names: the first whole number in it, so that
    `23`, `job 23` and `task-23` all name `task-23`; None if it holds no number."""
    number = re.search(r"\d+", reference)
    return None if number is None else f"task-{int(number[0])}"


def job_number(task_id: str) -> int:
    """The number on the notice of the job `task_id`."""
    return int(task_id.removeprefix("task-"))


def job_name(task_id: str) -> str:
    """`job 23`, the name a resident knows the job `task-23` by."""
    return f"job {job_number(task_id)}"
