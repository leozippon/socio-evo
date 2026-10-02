"""Work sessions: the agents at a work place claim, deliver and talk in rounds."""

from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision, Pass
from runtime.scenes import situations
from runtime.scenes.scene import Scene


class WorkSession(Scene):
    """Up to `rounds` rounds at a work place, in each of which every agent present decides
    at once. A round in which everyone passes ends the session."""

    kind = "work"
    allowed = (ActionKind.CLAIM_TASK, ActionKind.SUBMIT_WORK, ActionKind.SPEAK, ActionKind.PASS)

    def __init__(
        self, env: Environment, id: str, place: str, participants: Sequence[str], rounds: int
    ) -> None:
        super().__init__(env, id, place, participants)
        self.rounds = rounds

    def ask(self) -> list[str]:
        return list(self.participants)

    def situation(self, agent: str) -> str:
        others = [other for other in self.participants if other != agent]
        return situations.work(self.env, self.place, self.rounds, self.turns + 1, agent, others)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        await self.env.execute(
            agent, decision.action, time=time, scene=self.id, witnesses=self.participants
        )

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return self.turns >= self.rounds or all(
            isinstance(decision.action, Pass) for decision in decisions.values()
        )
