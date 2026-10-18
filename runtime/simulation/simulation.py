"""The run loop: triggers dispatched in order, evolution at night, checkpoints.

A day start opens the day in the environment, lets every agent plan, and expands into the
day's slot triggers and its day-end trigger. A slot moves the agents as planned, posts new jobs
if it is one of the configured postings, and plays a work session at every occupied work place
and a conversation at every social place with company, each until the place closes at the
latest; nothing else costs a model call. A resident who leaves either goes home until the
next slot moves it. A day end sends whoever is still out home (told as the place closing, for
a place that closes then), tells each worker privately what is still on its desk, so that the
ledger's moment and the diary have it among the evening's percepts, holds the evening ledger,
closes the day in the environment, hands every agent what it witnessed since its last
decision, lets every agent evolve, schedules the next day and writes a checkpoint.
Interventions change conditions or make announcements at their time.

A meeting is put up as a notice to everyone when its day starts, before anyone plans the
day. At its slot the clerk opens it to those at its place, who hold it as a `Meeting` scene in
place of the conversation there; its count is announced to everyone when the day ends, and
the enactment of an answer that carried is queued as an intervention for the next day's
start, so that it takes effect before anything else and is kept with the checkpoint.

A reply of an agent's that cannot be obtained in the bounded attempts does not end the run: the
moment passes without the agent doing anything, or the night step is skipped with nothing
committed for it, and either is recorded as a `lapse` event. A run whose lapses exceed the
configured share of its decisions and lapses fails, since it no longer shows what its
residents would do; any other failure of the model, such as an unreachable server, fails the
run at once.

Every decision is taken knowing the setting, what every resident knows of the town, which the
runtime composes from the calendar, the places and the environment's rules. The jobs of a
posting are drawn from the run's seed and the moment alone (see `Environment.post`), so the
same seed posts the same jobs whatever the residents did; every other draw comes from the
run's generator.
"""

import asyncio
import json
import logging
import os
import random
import time as wall
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import JsonValue, NonNegativeInt

from core.agent import Agent, AgentSeed, CognitionConfig
from core.agent.evolution import Evolver, History, Lapse, Version
from core.agent.evolution import Trigger as Cadence
from core.environment import Environment, EnvironmentConfig, Place, PlaceKind, TaskProvider, Trade
from core.interaction import EventKind, clock_of, day_of, time_at
from infrastructure.config import StrictModel
from infrastructure.llm import LLMClient
from infrastructure.storage import RunDirectory, RunStatus
from runtime.scenes import (
    Conversation,
    Meeting,
    Planning,
    Review,
    Scene,
    WorkSession,
    lapse,
    play,
    situations,
)
from runtime.scheduler import Trigger, TriggerKind, TriggerQueue
from runtime.simulation.config import Meeting as Called
from runtime.simulation.config import SimulationConfig

log = logging.getLogger(__name__)

MIN_LAPSES = 10
"""Lapses a run may have whatever their share, so that a short run or a small town is not
judged on its first one or two."""


@dataclass(frozen=True)
class Setup:
    """What a run is made of: its configuration, how agents evolve, the work of each trade
    the town posts, and the model behind every agent. The parts are built, and so validated,
    before the run exists."""

    simulation: SimulationConfig
    environment: EnvironmentConfig
    agents: tuple[AgentSeed, ...]
    cognition: CognitionConfig
    evolver: Evolver
    providers: Mapping[Trade, TaskProvider]
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
        self.seed = run.read_manifest().seed
        self.config = setup.simulation
        self.env = env
        self.agents = agents
        self.evolver = setup.evolver
        self.queue = queue
        self.rng = rng
        self.day = day
        """The last day completed."""
        self._stop = self.config.days
        self._met: dict[str, set[str]] = {}
        self._held: list[tuple[Called, Meeting | None]] = []
        """Today's meetings so far, each with its scene, None if nobody came."""
        self._started = wall.perf_counter()
        self._kinds: Counter[str] = Counter()
        """The kinds of the events in the first `_read` bytes of the event log."""
        self._read = 0

    @classmethod
    def create(cls, run: RunDirectory, setup: Setup) -> "Simulation":
        """Start the run in the new run directory `run`, seeded with its manifest's seed, and
        write the checkpoint of day 0. A failure marks the run failed."""
        try:
            ids = [seed.profile.name for seed in setup.agents]
            env = Environment.create(setup.environment, ids, setup.providers, run.events_path)
            setting, agents = setup.environment.setting, {}
            for seed in setup.agents:
                path = run.agent_dir(seed.profile.name)
                agent = Agent.create(path, seed, setup.client, setup.cognition, setting)
                History.init(agent.path, agent.id, setting.start_date).commit_experience(0)
                agents[agent.id] = agent
            calendar = setup.simulation.calendar
            queue = TriggerQueue([Trigger(time=calendar.start(1), kind=TriggerKind.DAY_START)])
            for intervention in setup.simulation.changes:
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
        for provider in setup.providers.values():
            if hasattr(provider, "restore_checkpoint"):
                provider.restore_checkpoint(checkpoint.day)
        env = Environment.restore(
            setup.environment, checkpoint.environment, setup.providers, run.events_path
        )
        agents, setting = {}, setup.environment.setting
        for agent_id, commit in checkpoint.agents.items():
            path = run.agent_dir(agent_id)
            History(path).reset(commit)
            agents[agent_id] = Agent.load(path, setup.client, setup.cognition, setting)
        rng = random.Random()
        rng.setstate(checkpoint.rng)
        run.update_manifest(status=RunStatus.RUNNING, ended_at=None)
        queue = TriggerQueue(checkpoint.queue)
        return cls(run, setup, env, agents, queue, rng, checkpoint.day)

    async def run(self, until_day: int | None = None) -> RunStatus:
        """Run through the last day, or only through `until_day`, and return the final
        status: completed, or interrupted when stopped early. An exception marks the run
        failed (interrupted for a cancellation or keyboard interrupt) and propagates. Agents
        act and evolve concurrently; when one of them fails, the others are cancelled first,
        so nothing changes after the run has failed, and the failures propagate together as
        an ExceptionGroup."""
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
        self._met, self._held = {agent: set() for agent in self.agents}, []
        starts = dict(calendar.slot_times(day))
        for called in self._meetings(day):
            clock = clock_of(starts[called.at])
            self.env.emit(
                EventKind.ANNOUNCEMENT,
                situations.notice(self.env, called.place, clock, called.question, called.options),
                time=time,
                audience=self.env.agents,
                payload={
                    "meeting": called.id,
                    "place": called.place,
                    "question": called.question,
                    "options": list(called.options),
                },
            )
        planning = Planning(
            self.env,
            f"day-{day:04d}/planning",
            list(self.agents),
            calendar,
            start=time,
            posting=self._next_posting(time),
        )
        await self._play([planning])
        for slot, start in calendar.slot_times(day):
            payload = {"slot": slot, "destinations": planning.destinations(slot)}
            self.queue.push(Trigger(time=start, kind=TriggerKind.SLOT, payload=payload))
        self.queue.push(Trigger(time=calendar.end(day), kind=TriggerKind.DAY_END))

    async def _slot(self, time: int, payload: dict[str, JsonValue]) -> None:
        self._move(payload["destinations"], time)
        if payload["slot"] in self.config.postings:
            self.env.post(time, self.seed)
        day, settings = day_of(time), self.config.scenes
        prefix, ends = f"day-{day:04d}/{payload['slot']}/", self.config.calendar.slot_ends(day)
        slot = payload["slot"]
        due = {called.place: called for called in self._meetings(day) if called.at == slot}
        scenes: list[Scene] = []
        for place in self.env.world.places.values():
            here = self.env.world.occupants(place.id)
            if (called := due.get(place.id)) is not None:
                if not here:
                    self._held.append((called, None))
                    continue
                self.env.emit(
                    EventKind.ANNOUNCEMENT,
                    situations.opening(called.question, called.options),
                    time=time,
                    audience=here,
                    place=place.id,
                    scene=called.id,
                    payload={"meeting": called.id},
                )
                scene = Meeting(
                    self.env,
                    called.id,
                    place.id,
                    here,
                    start=time,
                    step=settings.turn_minutes,
                    max_turns=settings.conversation_turns,
                    until=self._closing(place, time),
                    rng=self.rng,
                    question=called.question,
                    options=called.options,
                )
                self._held.append((called, scene))
            elif place.kind is PlaceKind.WORK and here:
                closing = place.closing(clock_of(time))
                closes = closing is not None and time_at(day, closing) <= ends[payload["slot"]]
                scene = WorkSession(
                    self.env,
                    prefix + place.id,
                    place.id,
                    here,
                    start=time,
                    until=time_at(day, closing) if closes else ends[payload["slot"]],
                    rounds=settings.work_rounds,
                    closes=closes,
                    posting=self._next_posting(time),
                )
            elif place.kind is PlaceKind.SOCIAL and len(here) > 1:
                scene = Conversation(
                    self.env,
                    prefix + place.id,
                    place.id,
                    here,
                    start=time,
                    step=settings.turn_minutes,
                    max_turns=settings.conversation_turns,
                    until=self._closing(place, time),
                    rng=self.rng,
                )
            else:
                continue
            scenes.append(scene)
            for agent in here:
                self._met[agent].update(other for other in here if other != agent)
        await self._play(scenes)

    async def _end_day(self, time: int) -> None:
        day = day_of(time)
        for called, scene in self._held:
            self._count(called, scene, time)
        end = self.config.calendar.day_end
        closing = {
            place.id
            for place in self.env.world.places.values()
            if place.kind is not PlaceKind.HOME and (not place.hours or place.spans()[-1][1] == end)
        }
        self._move(self.env.config.homes, time, closing)
        self._desks(time)
        met = {
            agent: [other for other in self.agents if other in others]
            for agent, others in self._met.items()
            if others
        }
        if met:
            await self._play([Review(self.env, f"day-{day:04d}/review", met, start=time)])
        self.env.end_day(time)
        for agent_id, agent in self.agents.items():
            agent.perceive(self.env.perceive(agent_id))

        cadences = self.config.calendar.cadences(day)
        async with asyncio.TaskGroup() as group:
            evolving = [
                group.create_task(self._evolve(agent, cadences, time))
                for agent in self.agents.values()
            ]
        for agent, steps in zip(self.agents, evolving, strict=True):
            for step in steps.result():
                if isinstance(step, Lapse):
                    level, trigger = str(step.level), str(step.trigger)
                    lapse(self.env, agent, step.error, time=time, level=level, trigger=trigger)
                    continue
                self.env.emit(
                    EventKind.EVOLUTION,
                    f"{agent}: {step.subject}",
                    time=time,
                    actor=agent,
                    payload={
                        "agent": agent,
                        "level": str(step.level),
                        "trigger": str(step.trigger),
                        "commit": step.commit,
                        "subject": step.subject,
                    },
                )
        self._bound_lapses()

        if day < self.config.days:
            self.queue.push(
                Trigger(time=self.config.calendar.start(day + 1), kind=TriggerKind.DAY_START)
            )
        self.day = day
        if day % self.config.checkpoint_days == 0 or day == self._stop:
            self._checkpoint()
        log.info(
            "%s: day %d done in %.0f s; %d lapses in %d decisions so far",
            self.directory.root,
            day,
            wall.perf_counter() - self._started,
            self._kinds[EventKind.LAPSE],
            self._kinds[EventKind.DECISION],
        )

    def _desks(self, time: int) -> None:
        """Tell each agent that holds a job, privately, what is still on its desk."""
        for agent in self.agents:
            if (desk := self.env.desk_view(agent)) is not None:
                task = self.env.board.claim_of(agent).task.id
                self.env.emit(
                    EventKind.DESK, desk, time=time, audience=[agent], payload={"task_id": task}
                )

    def _closing(self, place: Place, time: int) -> int:
        """When `place`, open at `time`, closes: at the end of its span, or, for a place
        without hours, when the day ends."""
        day, closes = day_of(time), place.closing(clock_of(time))
        return self.config.calendar.end(day) if closes is None else time_at(day, closes)

    def _meetings(self, day: int) -> list[Called]:
        return [called for called in self.config.meetings if called.day == day]

    def _count(self, called: Called, scene: Meeting | None, time: int) -> None:
        """Announce the count of the meeting `called`, held as `scene` (None if nobody came),
        and queue the enactment of the answer that carried, if it has one, for the next day's
        start."""
        asked = [] if scene is None else scene.voters or []
        counts = {option: 0 if scene is None else scene.count(option) for option in called.options}
        carried = None if scene is None else scene.carried()
        self.env.emit(
            EventKind.ANNOUNCEMENT,
            situations.count(self.env, called.place, called.question, counts, len(asked), carried),
            time=time,
            audience=self.env.agents,
            payload={
                "meeting": called.id,
                "asked": asked,
                "counts": counts,
                "carried": carried,
            },
        )
        if changes := called.enacts.get(carried or ""):
            start = self.config.calendar.start(day_of(time) + 1)
            enactment = {"conditions": changes, "announcement": None, "meeting": called.id}
            self.queue.push(Trigger(time=start, kind=TriggerKind.INTERVENTION, payload=enactment))

    def _intervene(self, time: int, payload: dict[str, JsonValue]) -> None:
        if payload["conditions"]:
            self.env.change_conditions(
                payload["conditions"], time=time, meeting=payload.get("meeting")
            )
        if payload["announcement"] is not None:
            self.env.emit(
                EventKind.ANNOUNCEMENT, payload["announcement"], time=time, audience=self.env.agents
            )

    def _move(
        self, destinations: Mapping[str, str], time: int, closing: Collection[str] = ()
    ) -> None:
        """Move every agent to its destination, or home if reality refuses that move, in an
        order drawn at random: a move is seen only by those already there, so a fixed order
        would show some agents as always early. A move from one of the places `closing` is
        told as that place closing."""
        order, homes = list(self.agents), self.env.config.homes
        self.rng.shuffle(order)
        for agent in order:
            leaving = self.env.world.locations[agent] in closing
            moved = self.env.move(agent, destinations[agent], time=time, closing=leaving)
            if moved and moved[0].kind is EventKind.ACTION_REJECTED:
                self.env.move(agent, homes[agent], time=time)

    async def _play(self, scenes: list[Scene]) -> None:
        await play(self.env, self.agents, scenes, self.rng, self._setting, lapses=True)
        self._bound_lapses()

    def _bound_lapses(self) -> None:
        """Raise RuntimeError if the run's lapses, counted in its event log, exceed the
        configured share of its decisions and lapses and number at least MIN_LAPSES."""
        with self.directory.events_path.open("rb") as events:
            events.seek(self._read)
            for line in events:
                self._kinds[json.loads(line)["kind"]] += 1
            self._read = events.tell()
        lapses = self._kinds[EventKind.LAPSE]
        asked = lapses + self._kinds[EventKind.DECISION]
        if lapses >= MIN_LAPSES and lapses > self.config.max_lapse_share * asked:
            raise RuntimeError(
                f"{lapses} of {asked} decisions and night steps lapsed for want of a valid reply, "
                f"more than the {self.config.max_lapse_share:.1%} a run may lose"
            )

    def _setting(self, agent: str) -> str:
        """What `agent` knows of the town now."""
        config = self.config
        return situations.setting(self.env, config.calendar, config.postings, agent)

    def _next_posting(self, time: int) -> int | None:
        """When new notices next go up after `time`."""
        return situations.next_posting(self.config.calendar, self.config.postings, time)

    async def _evolve(
        self, agent: Agent, cadences: tuple[Cadence, ...], time: int
    ) -> list[Version | Lapse]:
        """Commit the day's experience, then evolve on each due cadence in turn."""
        History(agent.path, agent.setting.start_date).commit_experience(time)
        versions: list[Version | Lapse] = []
        for cadence in cadences:
            versions += await self.evolver.evolve(agent, cadence, time)
        return versions

    def _checkpoint(self) -> None:
        for provider in self.env.providers.values():
            if hasattr(provider, "checkpoint"):
                provider.checkpoint(self.day)
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
