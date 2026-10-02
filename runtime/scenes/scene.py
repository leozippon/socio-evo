"""Scenes, and the driver that plays them turn by turn.

A scene decides who is asked in each turn, what each of them is told and what becomes of
their decisions; what an action means stays with the Environment. The driver plays any
number of scenes side by side, and a turn is common to all of them: it asks every agent the
scenes name, all concurrently, records each decision as a truth-only `decision` event, and
then has the scenes carry the decisions out one at a time in an order drawn at random. The
agents who claimed the same task in the turn, wherever they are, are told that order. Which
claim on the shared board succeeds is thus decided by the draw alone, never by which place
or agent is listed first; model latency never changes what happens; and with deterministic
replies a run is exactly reproducible. If an agent fails to decide, the others are cancelled
before the failure propagates.
"""

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import ClassVar

from core.agent import Agent
from core.environment import Environment
from core.interaction import ActionKind, ClaimTask, Decision, EventKind, Observation
from runtime.scenes import situations


class Scene(ABC):
    """Agents meeting at `place` (None for a scene each agent attends where it is).

    `participants` are the agents present at the start; `turns` counts the turns played.
    """

    kind: ClassVar[str]
    allowed: ClassVar[tuple[ActionKind, ...]]

    def __init__(
        self, env: Environment, id: str, place: str | None, participants: Sequence[str]
    ) -> None:
        self.env = env
        self.id = id
        self.place = place
        self.participants = tuple(participants)
        self.turns = 0

    @abstractmethod
    def ask(self) -> list[str]:
        """The agents whose decisions the next turn needs; never empty until the scene is
        over."""

    @abstractmethod
    def situation(self, agent: str) -> str:
        """What `agent` is told about its circumstances and options now."""

    @abstractmethod
    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        """Carry out `agent`'s decision in the turn that takes place at `time`."""

    @abstractmethod
    def over(self, decisions: Mapping[str, Decision]) -> bool:
        """Whether the scene ends with the turn just played, the `turns`-th, all of whose
        `decisions` have been carried out."""


async def play(
    env: Environment,
    agents: Mapping[str, Agent],
    scenes: Sequence[Scene],
    start: int,
    step: int,
    rng: random.Random,
) -> None:
    """Play `scenes` until all are over; turn n of each takes place at `start + n * step`,
    and `rng` draws the order in which each turn's decisions are carried out."""
    for scene in scenes:
        env.emit(
            EventKind.SCENE_STARTED,
            f"The {scene.kind} scene {scene.id} started with {', '.join(scene.participants)}.",
            time=start,
            place=scene.place,
            scene=scene.id,
            payload={"kind": scene.kind, "participants": list(scene.participants)},
        )
    active, time = list(scenes), start
    while active:
        asked = [(scene, agent) for scene in active for agent in scene.ask()]
        observations = [
            Observation(
                agent=agent,
                time=time,
                place=env.world.locations[agent],
                scene=scene.id,
                situation=scene.situation(agent),
                percepts=env.perceive(agent),
                allowed=scene.allowed,
            )
            for scene, agent in asked
        ]
        async with asyncio.TaskGroup() as group:
            deciding = [
                group.create_task(agents[observation.agent].act(observation))
                for observation in observations
            ]
        turn = [
            (scene, agent, task.result())
            for (scene, agent), task in zip(asked, deciding, strict=True)
        ]
        for scene, agent, decision in turn:
            env.emit(
                EventKind.DECISION,
                f"{agent} chose {decision.action.kind}.",
                time=time,
                actor=agent,
                place=env.world.locations[agent],
                scene=scene.id,
                payload={
                    "thought": decision.thought,
                    "action": decision.action.model_dump(mode="json"),
                },
            )
        rng.shuffle(turn)
        _announce_draws(env, turn, time)
        for scene, agent, decision in turn:
            await scene.carry_out(agent, decision, time)

        going_on = []
        for scene in active:
            scene.turns += 1
            decisions = {agent: decision for owner, agent, decision in turn if owner is scene}
            if not scene.over(decisions):
                going_on.append(scene)
                continue
            env.emit(
                EventKind.SCENE_ENDED,
                f"The {scene.kind} scene {scene.id} ended after {scene.turns} turns.",
                time=time,
                place=scene.place,
                scene=scene.id,
                payload={"kind": scene.kind, "turns": scene.turns},
            )
        active, time = going_on, time + step


def _announce_draws(
    env: Environment, turn: Sequence[tuple[Scene, str, Decision]], time: int
) -> None:
    """Tell the agents who claimed the same task in `turn`, its decisions in the order
    drawn, the order in which their claims are taken."""
    claims: dict[str, list[str]] = {}
    for _, agent, decision in turn:
        if isinstance(action := decision.action, ClaimTask):
            claims.setdefault(action.task_id, []).append(agent)
    for task, claimants in claims.items():
        if len(claimants) > 1:
            env.emit(
                EventKind.DRAW,
                situations.DRAW.format(
                    people=situations.names(sorted(claimants)),
                    task=task,
                    order=", ".join(claimants),
                ),
                time=time,
                audience=claimants,
                payload={"task_id": task, "order": claimants},
            )
