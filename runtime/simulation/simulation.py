"""The run loop: triggers dispatched in order, evolution at night, checkpoints.

A day start opens the day in the environment, lets every agent plan, and expands into the
day's slot triggers and its day-end trigger. A slot moves the agents as planned and plays a
work session at every occupied work place and a conversation at every social place with
company; nothing else costs a model call. A day end sends everyone home, holds the evening
review, closes the day in the environment, hands every agent what it witnessed since its
last decision, lets every agent evolve, schedules the next day and writes a checkpoint.
Interventions change conditions or make announcements at their time.
"""

import asyncio
import logging
import os
import random
import time as wall
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import JsonValue, NonNegativeInt

from core.agent import Agent, AgentSeed, CognitionConfig
from core.agent.evolution import EvolutionConfig, Evolver, History, Version
from core.agent.evolution import Trigger as Cadence
from core.environment import Environment, EnvironmentConfig, PlaceKind, TaskProvider
from core.interaction import EventKind, day_of
from infrastructure.config import StrictModel
from infrastructure.llm import LLMClient
from infrastructure.storage import RunDirectory, RunStatus
from runtime.scenes import Conversation, Planning, Review, Scene, WorkSession, play
from runtime.scheduler import Trigger, TriggerKind, TriggerQueue
from runtime.simulation.config import SimulationConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Setup:
    """What a run is made of: its configuration, the work and the model behind every agent."""

    simulation: SimulationConfig
    environment: EnvironmentConfig
    agents: tuple[AgentSeed, ...]
    cognition: CognitionConfig
    evolution: EvolutionConfig
    provider: TaskProvider
    client: LLMClient


class Checkpoint(StrictModel):
    """The state at the end of `day` (0 before the first): reality, the pending triggers, the
    random generator and each agent's commit."""

    day: NonNegativeInt
    environment: dict[str, JsonValue]
    queue: tuple[Trigger, ...]
    rng: tuple[int, tuple[int, ...], float | None]
    agents: dict[str, str]


class Simulation:
    """One society run in `run`. Obtain one through `create` or `resume`, then `run` it."""

    def __init__(
        self,
        run: RunDirectory,
        setup: Setup,
        env: Environment,
        agents: dict[str, Agent],
        queue: TriggerQueue,
        rng: random.Random,
        day: int,
    ) -> None:
        self.directory = run
        self.config = setup.simulation
        self.env = env
        self.agents = agents
        self.evolver = Evolver(setup.evolution)
        self.queue = queue
        self.rng = rng
        self.day = day
        """The last day completed."""
        self._stop = self.config.days
        self._met: dict[str, set[str]] = {}
        self._started = wall.perf_counter()

    @classmethod
    def create(cls, run: RunDirectory, setup: Setup) -> "Simulation":
        """Start the run in the new run directory `run`, seeded with its manifest's seed, and
        write the checkpoint of day 0. A failure marks the run failed."""
        try:
            ids = [seed.profile.name for seed in setup.agents]
            env = Environment.create(setup.environment, ids, setup.provider, run.events_path)
            agents = {}
            for seed in setup.agents:
                agent = Agent.create(
                    run.agent_dir(seed.profile.name), seed, setup.client, setup.cognition
                )
                History.init(agent.path, agent.id).commit_experience(0)
                agents[agent.id] = agent
            calendar = setup.simulation.calendar
            queue = TriggerQueue([Trigger(time=calendar.start(1), kind=TriggerKind.DAY_START)])
            for intervention in setup.simulation.interventions:
                queue.push(
                    Trigger(
                        time=intervention.time(calendar),
                        kind=TriggerKind.INTERVENTION,
                        payload=intervention.model_dump(
                            mode="json", include={"conditions", "announcement"}
                        ),
                    )
                )
            rng = random.Random(run.read_manifest().seed)
            simulation = cls(run, setup, env, agents, queue, rng, 0)
            simulation._checkpoint()
        except BaseException:
            _finish(run, RunStatus.FAILED)
            raise
        return simulation

    @classmethod
    def resume(cls, run: RunDirectory, setup: Setup) -> "Simulation":
        """Continue `run` from its latest checkpoint: the event log is cut back to it, every
        agent is reset to its commit, and the run is marked running again.

        Raises ValueError for a completed run and FileNotFoundError without a checkpoint.
        """
        if run.read_manifest().status is RunStatus.COMPLETED:
            raise ValueError(f"{run.root} is already completed")
        path = run.latest_checkpoint()
        if path is None:
            raise FileNotFoundError(f"{run.root} has no checkpoint")
        checkpoint = Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
        env = Environment.restore(
            setup.environment, checkpoint.environment, setup.provider, run.events_path
        )
        agents = {}
        for agent_id, commit in checkpoint.agents.items():
            History(run.agent_dir(agent_id)).reset(commit)
            agents[agent_id] = Agent.load(run.agent_dir(agent_id), setup.client, setup.cognition)
        rng = random.Random()
        rng.setstate(checkpoint.rng)
        run.update_manifest(status=RunStatus.RUNNING, ended_at=None)
        queue = TriggerQueue(checkpoint.queue)
        return cls(run, setup, env, agents, queue, rng, checkpoint.day)

    async def run(self, until_day: int | None = None) -> RunStatus:
        """Run through the last day, or only through `until_day`, and return the final
        status: completed, or interrupted when stopped early. An exception marks the run
        failed (interrupted for a cancellation or keyboard interrupt) and propagates."""
        self._stop = self.config.days if until_day is None else min(until_day, self.config.days)
        try:
            while self.day < self._stop:
                await self._dispatch(self.queue.pop())
        except Exception:
            _finish(self.directory, RunStatus.FAILED)
            raise
        except BaseException:
            _finish(self.directory, RunStatus.INTERRUPTED)
            raise
        status = RunStatus.COMPLETED if self.day == self.config.days else RunStatus.INTERRUPTED
        _finish(self.directory, status)
        return status

    async def _dispatch(self, trigger: Trigger) -> None:
        match trigger.kind:
            case TriggerKind.DAY_START:
                await self._start_day(trigger.time)
            case TriggerKind.SLOT:
                await self._slot(trigger.time, trigger.payload)
            case TriggerKind.DAY_END:
                await self._end_day(trigger.time)
            case TriggerKind.INTERVENTION:
                self._intervene(trigger.time, trigger.payload)

    async def _start_day(self, time: int) -> None:
        day, calendar = day_of(time), self.config.calendar
        self._started = wall.perf_counter()
        self.env.start_day(time, self.rng)
        self._met = {agent: set() for agent in self.agents}
        planning = Planning(self.env, f"day-{day:04d}/planning", list(self.agents), calendar, day)
        await self._play([planning], time)
        for slot, start in calendar.slot_times(day):
            payload = {"slot": slot, "destinations": planning.destinations(slot)}
            self.queue.push(Trigger(time=start, kind=TriggerKind.SLOT, payload=payload))
        self.queue.push(Trigger(time=calendar.end(day), kind=TriggerKind.DAY_END))

    async def _slot(self, time: int, payload: dict[str, JsonValue]) -> None:
        self._move(payload["destinations"], time)
        scenes: list[Scene] = []
        prefix, settings = f"day-{day_of(time):04d}/{payload['slot']}/", self.config.scenes
        for place in self.env.world.places.values():
            here = self.env.world.occupants(place.id)
            if place.kind is PlaceKind.WORK and here:
                scene = WorkSession(
                    self.env, prefix + place.id, place.id, here, settings.work_rounds, self.rng
                )
            elif place.kind is PlaceKind.SOCIAL and len(here) > 1:
                scene = Conversation(
                    self.env,
                    prefix + place.id,
                    place.id,
                    here,
                    settings.conversation_turns,
                    self.rng,
                )
            else:
                continue
            scenes.append(scene)
            for agent in here:
                self._met[agent].update(other for other in here if other != agent)
        await self._play(scenes, time)

    async def _end_day(self, time: int) -> None:
        day = day_of(time)
        self._move(self.env.config.homes, time)
        met = {
            agent: [other for other in self.agents if other in others]
            for agent, others in self._met.items()
            if others
        }
        if met:
            await self._play([Review(self.env, f"day-{day:04d}/review", met, day)], time)
        self.env.end_day(time)
        for agent_id, agent in self.agents.items():
            agent.perceive(self.env.perceive(agent_id))

        cadences = self.config.calendar.cadences(day)
        steps = await asyncio.gather(
            *(self._evolve(agent, cadences, time) for agent in self.agents.values())
        )
        for agent, versions in zip(self.agents, steps, strict=True):
            for version in versions:
                self.env.emit(
                    EventKind.EVOLUTION,
                    f"{agent}: {version.subject}",
                    time=time,
                    actor=agent,
                    payload={
                        "agent": agent,
                        "level": str(version.level),
                        "trigger": str(version.trigger),
                        "commit": version.commit,
                        "subject": version.subject,
                    },
                )

        if day < self.config.days:
            self.queue.push(
                Trigger(time=self.config.calendar.start(day + 1), kind=TriggerKind.DAY_START)
            )
        self.day = day
        if day % self.config.checkpoint_days == 0 or day == self._stop:
            self._checkpoint()
        log.info(
            "%s: day %d done in %.0f s",
            self.directory.root,
            day,
            wall.perf_counter() - self._started,
        )

    def _intervene(self, time: int, payload: dict[str, JsonValue]) -> None:
        if payload["conditions"]:
            self.env.change_conditions(payload["conditions"], time=time)
        if payload["announcement"] is not None:
            self.env.emit(
                EventKind.ANNOUNCEMENT, payload["announcement"], time=time, audience=self.env.agents
            )

    def _move(self, destinations: Mapping[str, str], time: int) -> None:
        """Move every agent to its destination, in an order drawn at random: a move is seen
        only by those already there, so a fixed order would show some agents as always early."""
        order = list(self.agents)
        self.rng.shuffle(order)
        for agent in order:
            self.env.move(agent, destinations[agent], time=time)

    async def _play(self, scenes: list[Scene], time: int) -> None:
        await play(self.env, self.agents, scenes, time, self.config.scenes.turn_minutes)

    async def _evolve(
        self, agent: Agent, cadences: tuple[Cadence, ...], time: int
    ) -> list[Version]:
        """Commit the day's experience, then evolve on each due cadence in turn."""
        History(agent.path).commit_experience(time)
        versions = []
        for cadence in cadences:
            versions += await self.evolver.evolve(agent, cadence, time)
        return versions

    def _checkpoint(self) -> None:
        checkpoint = Checkpoint(
            day=self.day,
            environment=self.env.state(),
            queue=tuple(self.queue.state()),
            rng=self.rng.getstate(),
            agents={
                agent_id: History(agent.path).head() for agent_id, agent in self.agents.items()
            },
        )
        path = self.directory.checkpoint_path(self.day)
        staging = path.with_suffix(".json.tmp")
        staging.write_text(checkpoint.model_dump_json(), encoding="utf-8")
        os.replace(staging, path)


def _finish(run: RunDirectory, status: RunStatus) -> None:
    run.update_manifest(status=status, ended_at=datetime.now(UTC))
