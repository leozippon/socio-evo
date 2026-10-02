"""Conversations: the agents at a social place take turns."""

import random
from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision, Leave, Speak
from runtime.scenes import situations
from runtime.scenes.scene import Scene


class Conversation(Scene):
    """Agents at a social place speak in turn, in an order shuffled with `rng`, until fewer
    than two remain, everyone remaining has had a turn since anything was said, or
    `max_turns` turns have been played. Only those still present hear what is said."""

    kind = "conversation"
    allowed = (ActionKind.SPEAK, ActionKind.LEAVE, ActionKind.PASS)

    def __init__(
        self,
        env: Environment,
        id: str,
        place: str,
        participants: Sequence[str],
        max_turns: int,
        rng: random.Random,
    ) -> None:
        super().__init__(env, id, place, participants)
        self.max_turns = max_turns
        self.present = list(participants)
        rng.shuffle(self.present)
        self.next = 0
        self.silent = 0

    def ask(self) -> list[str]:
        return [self.present[self.next]]

    def situation(self, agent: str) -> str:
        others = [other for other in self.present if other != agent]
        return situations.conversation(self.env, self.place, others)

    async def resolve(self, decisions: Mapping[str, Decision], time: int) -> None:
        [(agent, decision)] = decisions.items()
        await self.env.execute(
            agent, decision.action, time=time, scene=self.id, witnesses=self.present
        )
        match decision.action:
            case Leave():
                self.present.remove(agent)
            case Speak():
                self.silent = 0
                self.next += 1
            case _:
                self.silent += 1
                self.next += 1
        if self.present:
            self.next %= len(self.present)
        self.done = (
            len(self.present) < 2
            or self.silent >= len(self.present)
            or self.turns >= self.max_turns
        )
