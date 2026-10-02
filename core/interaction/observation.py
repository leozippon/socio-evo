"""What the environment presents to one agent at a decision point."""

from pydantic import Field

from core.interaction.actions import ActionKind
from core.interaction.events import Percept
from core.interaction.time import SimTime
from infrastructure.config import StrictModel


class Observation(StrictModel):
    """One agent's view at a decision point.

    `situation` describes the circumstances in natural language, `percepts` are the events
    the agent witnessed since its previous observation, and `allowed` lists the action kinds
    it may choose from. Percepts cannot carry an event's payload or audience, and passing an
    Event where a Percept is expected is rejected.
    """

    agent: str
    time: SimTime
    place: str
    scene: str
    situation: str
    percepts: tuple[Percept, ...] = ()
    allowed: tuple[ActionKind, ...] = Field(min_length=1)
