"""What the environment presents to one agent at a decision point."""

from typing import Literal

from pydantic import Field

from core.interaction.card import Allowance
from core.interaction.events import EventKind, Percept
from core.interaction.time import SimTime
from infrastructure.config import StrictModel


class Observation(StrictModel):
    """One agent's view at a decision point.

    `setting` is the standing knowledge of the town that every resident has (its places and
    their hours, how the board and the ledger work), the same from moment to moment until
    the town's rules change; it may be empty. `situation` describes the present moment in
    natural language, `percepts` are the events the agent witnessed since its previous
    observation, and `allowed` holds, for each kind of thing it can do now, the values that
    are really possible (see `core.interaction.card`). `places` names the town's places by
    id as the agent knows them, so that what it remembers can say where it happened; it may
    be empty. `shown` names the kinds of event whose news the situation shows as it now
    stands (the notices on the board, the posted standings), so that the agent does not
    recall their percepts beside it. Percepts cannot carry an event's payload or audience,
    and passing an Event where a Percept is expected is rejected.
    """

    activity_id: str | None = None
    activity_kind: Literal["selection", "work", "conversation", "rest", "move"] | None = None
    activity_task_id: str | None = Field(default=None, pattern=r"^task-\d+$")

    own_task_id: str | None = Field(default=None, pattern=r"^task-\d+$")
    work_activity: bool = False
    work_feedback: tuple[str, ...] = ()
    operational_evidence: bool = False

    evidence: tuple[str, ...] = ()
    """Current desk evidence, budgeted ahead of historical memory; not new events."""

    decision_layer: Literal["act", "choose_activity", "activity_tool"] = "act"
    correction_context: str = ""
    goal_updates: bool = False
    agent: str
    time: SimTime
    place: str
    scene: str
    setting: str = ""
    situation: str
    percepts: tuple[Percept, ...] = ()
    allowed: tuple[Allowance, ...] = Field(min_length=1)
    places: dict[str, str] = Field(default_factory=dict)
    shown: tuple[EventKind, ...] = ()
