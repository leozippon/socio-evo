"""The evening ledger: agents who met someone today may mark them."""

from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision
from runtime.scenes import situations
from runtime.scenes.scene import Scene


class Review(Scene):
    """At `start`, in one turn, every agent in `met` may mark peers in the board's ledger; it
    is reminded of the people it shared a scene with today, as `met` lists them, but may mark
    anyone."""

    kind = "review"

    def __init__(
        self, env: Environment, id: str, met: Mapping[str, Sequence[str]], *, start: int
    ) -> None:
        super().__init__(env, id, None, list(met), start, 0)
        self.met = met

    def ask(self) -> list[str]:
        return list(self.participants)

    def allowed(self, agent: str) -> tuple[ActionKind, ...]:
        return (ActionKind.RATE_PEERS, ActionKind.PASS)

    def situation(self, agent: str) -> str:
        return situations.review(self.met[agent])

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        await self.env.execute(agent, decision.action, time=time, scene=self.id, witnesses=[agent])

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return True
