"""How long scenes last."""

from pydantic import PositiveInt

from infrastructure.config import StrictModel


class SceneConfig(StrictModel):
    """A work session has at most `work_rounds` rounds, spread evenly over the part of the day
    until the work place closes or the part ends; a conversation has at most
    `conversation_turns` turns, `turn_minutes` apart."""

    work_rounds: PositiveInt = 3
    conversation_turns: PositiveInt = 12
    turn_minutes: PositiveInt = 5

    @property
    def conversation_minutes(self) -> int:
        """The most minutes a conversation can last."""
        return self.conversation_turns * self.turn_minutes
