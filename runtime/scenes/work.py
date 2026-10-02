"""Work sessions: the agents at a work place claim, deliver and talk in rounds."""

import random
from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, ClaimTask, Decision, EventKind, Pass
from runtime.scenes import situations
from runtime.scenes.scene import Scene


class WorkSession(Scene):
    """Up to `rounds` rounds at a work place. In each round every agent present decides at
    once; the decisions are then carried out in an order shuffled with `rng`, so contested
    claims resolve reproducibly, and the claimants of a contested task are told that order.
    A round in which everyone passes ends the session."""

    kind = "work"
    allowed = (ActionKind.CLAIM_TASK, ActionKind.SUBMIT_WORK, ActionKind.SPEAK, ActionKind.PASS)

    def __init__(
        self,
        env: Environment,
        id: str,
        place: str,
        participants: Sequence[str],
        rounds: int,
        rng: random.Random,
    ) -> None:
        super().__init__(env, id, place, participants)
        self.rounds = rounds
        self.rng = rng

    def ask(self) -> list[str]:
        return list(self.participants)

    def situation(self, agent: str) -> str:
        others = [other for other in self.participants if other != agent]
        return situations.work(self.env, self.place, self.rounds, self.turns + 1, agent, others)

    async def resolve(self, decisions: Mapping[str, Decision], time: int) -> None:
        order = list(decisions)
        self.rng.shuffle(order)
        claims: dict[str, list[str]] = {}
        for agent in order:
            if isinstance(action := decisions[agent].action, ClaimTask):
                claims.setdefault(action.task_id, []).append(agent)
        for task, claimants in claims.items():
            if len(claimants) > 1:
                self.env.emit(
                    EventKind.DRAW,
                    situations.DRAW.format(
                        people=situations.names(sorted(claimants, key=self.participants.index)),
                        task=task,
                        order=", ".join(claimants),
                    ),
                    time=time,
                    audience=claimants,
                    place=self.place,
                    scene=self.id,
                    payload={"task_id": task, "order": claimants},
                )
        for agent in order:
            await self.env.execute(
                agent,
                decisions[agent].action,
                time=time,
                scene=self.id,
                witnesses=self.participants,
            )
        self.done = self.turns >= self.rounds or all(
            isinstance(decision.action, Pass) for decision in decisions.values()
        )
