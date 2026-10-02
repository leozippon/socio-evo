"""Scenes, and the driver that plays them turn by turn.

A scene decides who is asked in each turn, what each of them is told and what becomes of
their decisions; what an action means stays with the Environment. The driver plays any
number of scenes side by side. In each turn it asks every agent the scenes name, all
concurrently, then goes through the scenes in order, recording each decision as a
truth-only `decision` event before the scene resolves it. Model latency therefore never
changes what happens, and with deterministic replies a run is exactly reproducible.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import ClassVar

from core.agent import Agent
from core.environment import Environment
from core.interaction import ActionKind, Decision, EventKind, Observation


class Scene(ABC):
    """Agents meeting at `place` (None for a scene each agent attends where it is).

    `participants` are the agents present at the start; `turns` counts the turns played;
    the driver stops asking once `done` is set.
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
        self.done = False

    @abstractmethod
    def ask(self) -> list[str]:
        """The agents whose decisions the next turn needs; never empty before `done`."""

    @abstractmethod
    def situation(self, agent: str) -> str:
        """What `agent` is told about its circumstances and options now."""

    @abstractmethod
    async def resolve(self, decisions: Mapping[str, Decision], time: int) -> None:
        """Carry out the decisions of the turn just played, the `turns`-th, at `time`."""


async def play(
    env: Environment, agents: Mapping[str, Agent], scenes: Sequence[Scene], start: int, step: int
) -> None:
    """Play `scenes` until all are done; turn n of each takes place at `start + n * step`."""
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
        decided = await asyncio.gather(
            *(agents[observation.agent].act(observation) for observation in observations)
        )
        for scene in active:
            decisions = {
                agent: decision
                for (owner, agent), decision in zip(asked, decided, strict=True)
                if owner is scene
            }
            for agent, decision in decisions.items():
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
            scene.turns += 1
            await scene.resolve(decisions, time)
            if scene.done:
                env.emit(
                    EventKind.SCENE_ENDED,
                    f"The {scene.kind} scene {scene.id} ended after {scene.turns} turns.",
                    time=time,
                    place=scene.place,
                    scene=scene.id,
                    payload={"kind": scene.kind, "turns": scene.turns},
                )
        active = [scene for scene in active if not scene.done]
        time += step
