"""Events, the immutable record of what happened, and percepts, a witness's view of one."""

from enum import StrEnum

from pydantic import Field, JsonValue, NonNegativeInt

from core.interaction.time import SimTime
from infrastructure.config import StrictModel


class EventKind(StrEnum):
    """The single vocabulary of event kinds."""

    DAY_STARTED = "day_started"
    DAY_ENDED = "day_ended"
    PLAN = "plan"
    MOVE = "move"
    SPEECH = "speech"
    LEFT = "left"
    TASK_POSTED = "task_posted"
    TASK_CLAIMED = "task_claimed"
    TASK_EXPIRED = "task_expired"
    """A claim not delivered by its deadline; the task returns to the board."""
    TASK_RETIRED = "task_retired"
    """An unclaimed task taken off the board after its shelf life; truth-only."""
    WORK_SUBMITTED = "work_submitted"
    """A delivery and its public result, as witnesses see it."""
    WORK_ASSESSED = "work_assessed"
    """The true quality of a delivery; truth-only."""
    PAYMENT = "payment"
    LIVING_COST = "living_cost"
    DEFECT_DISCOVERED = "defect_discovered"
    CLAWBACK = "clawback"
    RATING = "rating"
    ESTEEM_UPDATED = "esteem_updated"
    ACTION_REJECTED = "action_rejected"
    """An action reality could not honour; private to the actor, nothing changed."""
    ANNOUNCEMENT = "announcement"
    INTERVENTION = "intervention"
    DECISION = "decision"
    """An agent's private thought and chosen action, recorded before it is executed; truth-only."""
    DRAW = "draw"
    """The random order in which simultaneous claims on a task are taken; told to the claimants."""
    EVOLUTION = "evolution"
    SCENE_STARTED = "scene_started"
    SCENE_ENDED = "scene_ended"


class Percept(StrictModel):
    """A witness's view of an event: every event field except `payload` and `audience`."""

    seq: NonNegativeInt
    time: SimTime
    kind: EventKind
    actor: str | None = None
    place: str | None = None
    scene: str | None = None
    text: str


class Event(StrictModel):
    """Something that happened, numbered by `seq` in the event log.

    `audience` holds the ids of the agents who witnessed it and is empty for truth-only
    events. `text` is what a witness perceives. `payload` is structured truth for analysis
    and replay; it never reaches an agent.
    """

    seq: NonNegativeInt
    time: SimTime
    kind: EventKind
    actor: str | None = None
    place: str | None = None
    scene: str | None = None
    audience: tuple[str, ...] = ()
    text: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    def percept(self) -> Percept:
        """This event as its witnesses perceive it."""
        return Percept.model_validate(self.model_dump(exclude={"payload", "audience"}))
