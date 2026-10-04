"""Scenes, and the driver that plays them side by side.

A scene decides who is asked when, what each of them is told, what each may do with the
values that are really possible at that moment (the allowances of the answer card), and what
becomes of their decisions; what an action means stays with the Environment, which still
refuses, in the town's words, a choice that went stale within the moment. Each scene keeps its own
pace: its n-th turn takes place `step` minutes after the one before, from its `start`. The
driver plays any number of scenes in the order of time. The turns that fall at the same time,
whatever their scenes, are played together: everyone they ask decides concurrently, each
decision is recorded as a truth-only `decision` event, and the decisions are carried out one
at a time in an order drawn at random. The agents who asked for the same job at that moment,
wherever they are, are told that order, and after every such moment the board pairs by lot
the names put down for jobs for two. So which request on the shared board succeeds is decided
by the draw alone, never by which place or agent is listed first; model latency never changes
what happens; and with deterministic replies a run is exactly reproducible. If an agent fails
to decide, the others are cancelled before the failure propagates.
"""

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import ClassVar

from core.agent import Agent
from core.environment import Environment
from core.interaction import Allowance, ClaimTask, Decision, EventKind, Observation, job_id
from runtime.scenes import situations


class Scene(ABC):
    """Agents meeting at `place` (None for a scene each agent attends where it is), from
    `start`, a turn every `step` minutes.

    `participants` are the agents present at the start; `turns` counts the turns played.
    """

    kind: ClassVar[str]

    def __init__(
        self,
        env: Environment,
        id: str,
        place: str | None,
        participants: Sequence[str],
        start: int,
        step: int,
    ) -> None:
        self.env = env
        self.id = id
        self.place = place
        self.participants = tuple(participants)
        self.start = start
        self.step = step
        self.turns = 0

    @property
    def next_time(self) -> int:
        """When the next turn takes place."""
        return self.start + self.turns * self.step

    @abstractmethod
    def ask(self) -> list[str]:
        """The agents whose decisions the next turn needs; never empty until the scene is
        over."""

    @abstractmethod
    def allowed(self, agent: str) -> tuple[Allowance, ...]:
        """What `agent` may do now, with the values that are really possible."""

    @abstractmethod
    def situation(self, agent: str) -> str:
        """What `agent` is told about the moment and what it could do in it."""

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
    rng: random.Random,
    setting: Callable[[str], str],
) -> None:
    """Play `scenes` until all are over, in the order of their turns' times; `rng` draws the
    order in which the decisions of each moment are carried out and the board's lots, and
    `setting` is what each agent knows of the town."""
    for scene in scenes:
        env.emit(
            EventKind.SCENE_STARTED,
            f"The {scene.kind} scene {scene.id} started with {', '.join(scene.participants)}.",
            time=scene.start,
            place=scene.place,
            scene=scene.id,
            payload={"kind": scene.kind, "participants": list(scene.participants)},
        )
    active = list(scenes)
    while active:
        time = min(scene.next_time for scene in active)
        due = [scene for scene in active if scene.next_time == time]
        asked = [(scene, agent) for scene in due for agent in scene.ask()]
        observations = [
            Observation(
                agent=agent,
                time=time,
                place=env.world.locations[agent],
                scene=scene.id,
                setting=setting(agent),
                situation=scene.situation(agent),
                percepts=env.perceive(agent),
                allowed=scene.allowed(agent),
                places=situations.place_names(env, agent),
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
        env.pair_applicants(time, rng)

        for scene in due:
            scene.turns += 1
            decisions = {agent: decision for owner, agent, decision in turn if owner is scene}
            if not scene.over(decisions):
                continue
            active.remove(scene)
            env.emit(
                EventKind.SCENE_ENDED,
                f"The {scene.kind} scene {scene.id} ended after {scene.turns} turns.",
                time=time,
                place=scene.place,
                scene=scene.id,
                payload={"kind": scene.kind, "turns": scene.turns},
            )


def _announce_draws(
    env: Environment, turn: Sequence[tuple[Scene, str, Decision]], time: int
) -> None:
    """Tell the agents who reached for the same notice at this moment, its decisions in the
    order drawn, the order in which the clerk drew their names."""
    claims: dict[str, list[str]] = {}
    for _, agent, decision in turn:
        if isinstance(action := decision.action, ClaimTask):
            claims.setdefault(job_id(action.task_id) or action.task_id, []).append(agent)
    for task, claimants in claims.items():
        if len(claimants) > 1:
            env.emit(
                EventKind.DRAW,
                situations.draw(claimants, task),
                time=time,
                audience=claimants,
                payload={"task_id": task, "order": claimants},
            )
