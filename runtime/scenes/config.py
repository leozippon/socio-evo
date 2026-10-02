"""How long scenes last."""

from pydantic import PositiveInt

from infrastructure.config import StrictModel


class SceneConfig(StrictModel):
    """A work session lasts at most `work_rounds` rounds and a conversation at most
    `conversation_turns` turns; every turn takes `turn_minutes` of simulated time."""

    work_rounds: PositiveInt = 3
    conversation_turns: PositiveInt = 12
    turn_minutes: PositiveInt = 5

    @property
    def longest(self) -> int:
        """The most minutes a scene can last."""
        return max(self.work_rounds, self.conversation_turns) * self.turn_minutes
