"""Work: the agents at a work place take jobs, try and hand in code, and talk, hour by hour."""

from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision, Pass
from runtime.scenes import situations
from runtime.scenes.scene import Scene

TAKING = (
    ActionKind.CLAIM_TASK,
    ActionKind.SPEAK,
    ActionKind.GIVE,
    ActionKind.PASS,
)
"""What someone who works on no job may do at a work place."""
WORKING = (
    ActionKind.CHECK_WORK,
    ActionKind.SUBMIT_WORK,
    ActionKind.SPEAK,
    ActionKind.GIVE,
    ActionKind.PASS,
)
"""What someone working on a job may do at a work place."""


class WorkSession(Scene):
    """The agents at a work place from `start` until `until`, when the place closes or the
    part of the day ends, in at most `rounds` rounds spread evenly over that time; in each,
    every agent present decides at once. A round in which everyone carries on quietly ends
    the session: they work on until `until`. `closes` says whether `until` is the place's
    closing time."""

    kind = "work"

    def __init__(
        self,
        env: Environment,
        id: str,
        place: str,
        participants: Sequence[str],
        *,
        start: int,
        until: int,
        rounds: int,
        closes: bool,
    ) -> None:
        super().__init__(env, id, place, participants, start, (until - start) // rounds)
        self.rounds = rounds
        self.until = until
        self.closes = closes

    def ask(self) -> list[str]:
        return list(self.participants)

    def allowed(self, agent: str) -> tuple[ActionKind, ...]:
        kinds = TAKING if self.env.board.claim_of(agent) is None else WORKING
        if len(self.participants) > 1:
            return kinds
        return tuple(kind for kind in kinds if kind not in (ActionKind.SPEAK, ActionKind.GIVE))

    def situation(self, agent: str) -> str:
        others = [other for other in self.participants if other != agent]
        return situations.work(self.env, self.place, others, agent, self.until, self.closes)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        await self.env.execute(
            agent, decision.action, time=time, scene=self.id, witnesses=self.participants
        )

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return self.turns >= self.rounds or all(
            isinstance(decision.action, Pass) for decision in decisions.values()
        )
