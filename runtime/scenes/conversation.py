"""Conversations: the agents at a social place take turns."""

import random
from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import (
    Allowance,
    Decision,
    Give,
    Leave,
    MayGive,
    MayLeave,
    MayPass,
    MaySpeak,
    Speak,
)
from runtime.scenes import situations
from runtime.scenes.scene import Scene


class Conversation(Scene):
    """Agents at a social place, from `start`, speak in turn every `step` minutes, in an
    order shuffled with `rng`, until fewer than two remain, everyone remaining has had a turn
    since anything was said or given, `max_turns` turns have been played, or the next turn
    would fall at or after `until`, when the place closes. Only those still present hear
    what is said; one who leaves goes home."""

    kind = "conversation"

    def __init__(
        self,
        env: Environment,
        id: str,
        place: str,
        participants: Sequence[str],
        *,
        start: int,
        step: int,
        max_turns: int,
        until: int,
        rng: random.Random,
    ) -> None:
        super().__init__(env, id, place, participants, start, step)
        self.max_turns = max_turns
        self.until = until
        self.present = list(participants)
        rng.shuffle(self.present)
        self.next = 0
        self.silent = 0

    def ask(self) -> list[str]:
        return [self.present[self.next]]

    def allowed(self, agent: str) -> tuple[Allowance, ...]:
        others = tuple(other for other in self.present if other != agent)
        units = self.env.config.setting.currency.units
        return (MaySpeak(to=others), MayGive(to=others, units=units), MayLeave(), MayPass())

    def situation(self, agent: str) -> str:
        others = [other for other in self.present if other != agent]
        return situations.conversation(self.env, self.place, others, agent)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        await self.env.execute(
            agent, decision.action, time=time, scene=self.id, witnesses=self.present
        )
        match decision.action:
            case Leave():
                self.present.remove(agent)
            case Speak() | Give():
                self.silent = 0
                self.next += 1
            case _:
                self.silent += 1
                self.next += 1
        if self.present:
            self.next %= len(self.present)

    def lapsed(self, agent: str) -> None:
        """The turn passes to the next, as when `agent` carries on quietly."""
        self.silent += 1
        self.next = (self.next + 1) % len(self.present)

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return (
            len(self.present) < 2
            or self.silent >= len(self.present)
            or self.turns >= self.max_turns
            or self.next_time >= self.until
        )
