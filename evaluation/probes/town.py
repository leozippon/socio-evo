"""The town a probe is played in: a scratch copy of the evaluated run's town as it stood at the
end of the evaluated day, with the probe's strangers in it.

Everything a resident is shown in a probe is composed by the code that composes it in a run.
The environment is `core.environment.Environment`, built from the run's own configuration and
restored from the evaluated day's checkpoint: its conditions, so the rules of work read as the
resident knows them, every balance and standing, and the number the next notice will carry,
with an empty board and nobody holding a job. What leads up to a moment is made to happen in
that environment through its public methods: people move, notices go up, jobs are taken, code
is tried and handed in, people speak and hand over money, days end and begin; so every
percept is an event the environment itself recorded and worded, told to each witness in its
own words. The moment itself is a scene of `runtime.scenes` (a round of a work session, a turn
of a conversation, day planning) played by `runtime.scenes.play`, which builds the observation
as in a run: the setting, the situation, the percepts and the answer card.

The run's other residents are in town, at home, so that the standings and the names on a card
are those the resident knows. The strangers live in a lodging added for them, which no text
shows: a probe moves a stranger out of it before the resident reaches the place, and the
resident home first at night, so nobody sees them come or go from it. They decide as the
probe scripts them: in a scene they carry on quietly, and what they say or hand over is done
before it. Every scene asks the resident exactly once. The event log and the resident's
export live in a scratch directory that is removed afterwards (invariant 5).
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from core.agent import Agent
from core.environment import (
    Client,
    Environment,
    EnvironmentConfig,
    EnvironmentState,
    Part,
    Place,
    PlaceKind,
    Task,
)
from core.interaction import (
    Action,
    ClaimTask,
    Decision,
    Event,
    EventKind,
    Observation,
    Pass,
    clock_of,
    day_of,
    time_at,
)
from evaluation.probes.base import Step
from evaluation.probes.work import Postings, Work
from infrastructure.storage import read_jsonl
from runtime.scenes import Conversation, Planning, Scene, WorkSession, play, situations
from runtime.simulation import SimulationConfig

LODGING = "the lodging house"
"""The name of the strangers' home, which no text shows."""


@dataclass(frozen=True)
class Backdrop:
    """The evaluated run's town at the end of the evaluated `day`: its configuration, its days
    (calendar, postings and scenes) and the environment state of that day's checkpoint."""

    day: int
    environment: EnvironmentConfig
    simulation: SimulationConfig
    state: EnvironmentState

    def places(self, kind: PlaceKind) -> list[str]:
        """The ids of the town's places of `kind`, in the order of its configuration."""
        return [place.id for place in self.environment.places if place.kind is kind]

    def require(self, family: str, *, social: int = 1, last_opening: int = 0) -> None:
        """Raise ValueError unless the town has a work place, `social` social places, and
        every work place opens last for `last_opening` minutes or more."""
        works = [place for place in self.environment.places if place.kind is PlaceKind.WORK]
        if not works or len(self.places(PlaceKind.SOCIAL)) < social:
            raise ValueError(f"{family} needs a work place and {social} social place(s)")
        for place in works:
            if not place.spans():
                raise ValueError(f"{family} needs work places that close; {place.id} never does")
            opens, closes = place.spans()[-1]
            if time_at(1, closes) - time_at(1, opens) < last_opening:
                raise ValueError(f"{family}: {place.id} is open less than {last_opening} minutes")


class Recorder:
    """The resident, keeping every decision it makes with the observation it answered."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.steps: list[Step] = []

    async def act(self, observation: Observation) -> Decision:
        decision = await self.agent.act(observation)
        self.steps.append(Step(observation=observation, decision=decision))
        return decision


class Stranger:
    """Someone the probe introduces, who carries on quietly whenever a scene asks."""

    async def act(self, observation: Observation) -> Decision:
        return Decision(thought="", action=Pass())


class Town:
    """The probe town of `backdrop` for `resident`, with `strangers` at home in their lodging,
    each holding ten days of living cost; its log is kept in `directory` and `seed` seeds every
    draw. The probe's first day is the day after the evaluated one."""

    def __init__(
        self,
        backdrop: Backdrop,
        resident: Agent,
        strangers: Sequence[str],
        work: Work,
        directory: Path,
        seed: str,
    ) -> None:
        config, state = backdrop.environment, backdrop.state
        if clash := sorted(set(strangers) & set(state.cursors)):
            raise ValueError(f"strangers share names with residents of the town: {clash}")
        lodging = Place(
            id=_free_id("lodging", [place.id for place in config.places]),
            kind=PlaceKind.HOME,
            name=LODGING,
            description="",
            x=0,
            y=0,
            residents=tuple(strangers),
        )
        self.config = EnvironmentConfig.model_validate(
            {**config.model_dump(), "places": [*config.model_dump()["places"], lodging]}
        )
        homes = self.config.homes
        people = [*state.cursors, *strangers]
        purse = 10 * state.conditions.living_cost
        restored = state.model_copy(
            update={
                "event_count": 0,
                "cursors": dict.fromkeys(people, 0),
                "locations": {person: homes[person] for person in people},
                "balances": state.balances | dict.fromkeys(strangers, purse),
                "esteem": state.esteem | dict.fromkeys(strangers),
                "listings": (),
                "offers": (),
                "claims": (),
                "latent_defects": (),
            }
        )
        self.log = directory / "events.jsonl"
        self.log.touch(exist_ok=False)
        self.postings = Postings(work)
        self.env = Environment.restore(
            self.config, restored.model_dump(mode="json"), self.postings, self.log
        )
        self.work = work
        self.backdrop = backdrop
        self.recorder = Recorder(resident)
        self.resident = resident.id
        self.cast = {resident.id: self.recorder, **{name: Stranger() for name in strangers}}
        self.seed = seed
        self.rng = random.Random(seed)
        self.day = backdrop.day + 1

    # Where and when.

    def place(self, kind: PlaceKind, surface: int, offset: int = 0) -> str:
        """The town's place of `kind` that `surface` uses (the next one with `offset`)."""
        ids = self.backdrop.places(kind)
        if not ids:
            raise ValueError(f"the town has no {kind} place")
        return ids[(surface + offset) % len(ids)]

    def name(self, place: str) -> str:
        return self.env.world.places[place].name

    def opening(self, place: str, day: int, span: int = 0) -> int:
        """When `place` opens for its `span`-th span of the day (-1 for the last)."""
        return time_at(day, self._spans(place)[span][0])

    def closing(self, place: str, day: int) -> int:
        """When `place` closes last on `day`."""
        return time_at(day, self._spans(place)[-1][1])

    def evening(self, day: int) -> int:
        """When the last part of `day` begins."""
        return time_at(day, self.backdrop.simulation.calendar.slots[-1].start)

    def dawn(self, day: int) -> int:
        """When residents decide where to spend `day`."""
        return self.backdrop.simulation.calendar.start(day)

    @property
    def living_cost(self) -> int:
        return self.env.conditions.living_cost

    def money(self, amount: int) -> str:
        """`amount` in the town's currency, as a resident reads it."""
        return self.config.setting.currency.tell(amount)

    def balance(self, person: str) -> int:
        return self.env.economy.balances[person]

    # What happens.

    def move(self, person: str, place: str, time: int) -> None:
        """`person` goes to `place`, as the runtime moves people."""
        self._honoured(self.env.move(person, place, time=time))

    async def do(self, person: str, action: Action, time: int) -> list[Event]:
        """`person` does `action` where it is, witnessed by those there."""
        here = self.env.world.locations[person]
        events = await self.env.execute(
            person,
            action,
            time=time,
            scene=self._scene_id(time, here),
            witnesses=self.env.world.occupants(here),
        )
        return self._honoured(events)

    def post(self, time: int, parts: Sequence[Part], client: Client) -> Task:
        """Put up the notice of one job of `parts` for `client`, as a posting of the town puts
        notices up, priced by the town's conditions; its part rewards are what the posting
        pays before the town's multiplier and premium."""
        conditions = self.env.conditions
        changes = {
            "one_part_tasks": int(len(parts) == 1),
            "two_part_tasks": int(len(parts) == 2),
            "trusting_client_prob": float(client is Client.TRUSTING),
        }
        self.env.change_conditions(changes, time=time)
        self.postings.queue = list(parts)
        [posted] = self.env.post(time, self.seed)
        self.env.change_conditions({key: getattr(conditions, key) for key in changes}, time=time)
        return Task.model_validate(posted.payload["task"])

    def reward(self, amount: int, size: int = 1) -> int:
        """The part reward that a posting of a job of `size` parts prices at `amount` per part
        for each worker, give or take rounding."""
        conditions = self.env.conditions
        factor = conditions.reward_multiplier / size
        if size > 1:
            factor *= conditions.two_part_premium
        if factor <= 0:
            raise ValueError("the town pays nothing for work")
        return max(1, round(amount / factor))

    async def take_together(self, task: Task, partner: str, time: int) -> None:
        """The resident and `partner` take the job for two `task` as the town's rules have it:
        `partner` asks the clerk for it naming the resident, who takes it up naming them; or,
        where the clerk pairs names by lot, both put their names down and are paired."""
        if self.env.conditions.partner_choice:
            await self.do(partner, _claim(task, self.resident), time)
            await self.do(self.resident, _claim(task, partner), time)
        else:
            await self.do(partner, _claim(task, None), time)
            await self.do(self.resident, _claim(task, None), time)
            self.env.pair_applicants(time, self.rng)

    def night(self, day: int) -> None:
        """`day` ends as it does in a run (everyone home, living costs, the standings) and the
        next one begins; the resident goes home first, so it sees nobody leave."""
        end = self.backdrop.simulation.calendar.end(day)
        homes = self.config.homes
        for person in (self.resident, *(name for name in self.cast if name != self.resident)):
            self.move(person, homes[person], end)
        self.env.end_day(end)
        self.env.start_day(self.dawn(day + 1), self.rng)

    # The resident's moments.

    async def working(self, time: int) -> Decision:
        """One round of a work session at the resident's work place, at `time`, until it
        closes, with everyone there."""
        here = self.env.world.locations[self.resident]
        closes = self.env.world.places[here].closing(clock_of(time))
        if closes is None:
            raise ValueError(f"{here} is closed at {clock_of(time)}")
        scene = WorkSession(
            self.env,
            self._scene_id(time, here),
            here,
            self.env.world.occupants(here),
            start=time,
            until=time_at(day_of(time), closes),
            rounds=1,
            closes=True,
        )
        return await self._play(scene)

    async def talking(self, time: int) -> Decision:
        """The resident's turn in a conversation with everyone at its place, at `time` or one
        turn later."""
        here = self.env.world.locations[self.resident]
        present = self.env.world.occupants(here)
        closes = self.env.world.places[here].closing(clock_of(time))
        day = day_of(time)
        scene = Conversation(
            self.env,
            self._scene_id(time, here),
            here,
            present,
            start=time,
            step=self.backdrop.simulation.scenes.turn_minutes,
            max_turns=len(present),
            until=self.backdrop.simulation.calendar.end(day)
            if closes is None
            else time_at(day, closes),
            rng=self.rng,
        )
        return await self._play(scene)

    async def planning(self, time: int) -> dict[str, str]:
        """The resident's plan of the day that starts at `time`: a place id by part of day."""
        scene = Planning(
            self.env,
            f"day-{day_of(time):04d}/planning",
            [self.resident],
            self.backdrop.simulation.calendar,
            start=time,
        )
        await self._play(scene)
        return scene.itineraries[self.resident]

    # What the probe reads back.

    @property
    def steps(self) -> list[Step]:
        return self.recorder.steps

    def events(self, kind: EventKind | None = None) -> list[Event]:
        """The events of the town so far, of `kind` if given."""
        found = [Event.model_validate(line) for line in read_jsonl(self.log)]
        return [event for event in found if kind is None or event.kind is kind]

    def assessed(self) -> dict:
        """What reality found of the code the resident last tried or handed in: whether it
        passes the client's examples (`passed`) and its true quality (`quality`)."""
        runs = [
            event
            for event in self.events()
            if event.kind in (EventKind.WORK_CHECKED, EventKind.WORK_ASSESSED)
            and event.actor == self.resident
        ]
        return {key: runs[-1].payload[key] for key in ("passed", "quality")}

    def given(self, giver: str, recipient: str) -> int:
        """The money `giver` has handed `recipient` in this town."""
        return sum(
            event.payload["amount"]
            for event in self.events(EventKind.CREDITS_GIVEN)
            if (event.payload["giver"], event.payload["recipient"]) == (giver, recipient)
        )

    def _setting(self, agent: str) -> str:
        simulation = self.backdrop.simulation
        return situations.setting(self.env, simulation.calendar, simulation.postings, agent)

    async def _play(self, scene: Scene) -> Decision:
        before = len(self.steps)
        await play(self.env, self.cast, [scene], self.rng, self._setting)
        if len(self.steps) != before + 1:
            asked = len(self.steps) - before
            raise RuntimeError(f"the scene {scene.id} asked the resident {asked} times")
        return self.steps[-1].decision

    def _spans(self, place: str) -> list[tuple[str, str]]:
        spans = self.env.world.places[place].spans()
        if not spans:
            raise ValueError(f"{place} never closes")
        return spans

    def _scene_id(self, time: int, place: str) -> str:
        day = day_of(time)
        started = [
            name
            for name, start in self.backdrop.simulation.calendar.slot_times(day)
            if start <= time
        ]
        return f"day-{day:04d}/{started[-1] if started else 'dawn'}/{place}"

    @staticmethod
    def _honoured(events: list[Event]) -> list[Event]:
        if refused := [event.text for event in events if event.kind is EventKind.ACTION_REJECTED]:
            raise RuntimeError(f"the town refused a step of the probe: {refused}")
        return events


def _claim(task: Task, partner: str | None) -> Action:
    return ClaimTask(task_id=task.id, partner=partner)


def _free_id(base: str, taken: Sequence[str]) -> str:
    candidate, number = base, 1
    while candidate in taken:
        number += 1
        candidate = f"{base}-{number}"
    return candidate
