"""The evening review: agents who met someone today may rate them."""

from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision
from runtime.scenes import situations
from runtime.scenes.scene import Scene


class Review(Scene):
    """In one turn, every agent in `met` may rate peers; it is reminded of the people it
    shared a scene with today, as `met` lists them, but may rate anyone."""

    kind = "review"
    allowed = (ActionKind.RATE_PEERS, ActionKind.PASS)

    def __init__(
        self, env: Environment, id: str, met: Mapping[str, Sequence[str]], day: int
    ) -> None:
        super().__init__(env, id, None, list(met))
        self.met = met
        self.day = day

    def ask(self) -> list[str]:
        return list(self.participants)

    def situation(self, agent: str) -> str:
        return situations.review(self.day, self.met[agent])

    async def resolve(self, decisions: Mapping[str, Decision], time: int) -> None:
        for agent, decision in decisions.items():
            await self.env.execute(
                agent, decision.action, time=time, scene=self.id, witnesses=[agent]
            )
        self.done = True
