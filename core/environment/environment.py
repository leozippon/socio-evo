"""Reality: the facade over world and society that owns the event log.

Agents learn about reality only from the percepts of events they witness. Every method that
changes reality records what happened as events and returns them; agent-visible text is a
neutral description, and structured truth goes to the payload.
"""

import random
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from pydantic import JsonValue, NonNegativeInt, PositiveInt

from core.environment.conditions import Conditions
from core.environment.config import EnvironmentConfig
from core.environment.log import EventLog
from core.environment.rejection import Rejected
from core.environment.society import (
    Board,
    Claim,
    DecayedMean,
    Delivery,
    Economy,
    Listing,
    Reputation,
    Task,
    TaskProvider,
)
from core.environment.world import World
from core.interaction import (
    MINUTES_PER_DAY,
    Action,
    ClaimTask,
    Event,
    EventKind,
    Leave,
    Pass,
    Percept,
    PlanDay,
    RatePeers,
    Speak,
    SubmitWork,
    day_of,
)
from infrastructure.config import StrictModel


class EnvironmentState(StrictModel):
    """What a checkpoint holds of reality besides its config and the event log itself."""

    event_count: NonNegativeInt
    cursors: dict[str, NonNegativeInt]
    conditions: Conditions
    locations: dict[str, str]
    balances: dict[str, int]
    esteem: dict[str, DecayedMean | None]
    next_task_number: PositiveInt
    listings: tuple[Listing, ...]
    claims: tuple[Claim, ...]
    latent_defects: tuple[Delivery, ...]


class Environment:
    """Reality for a fixed set of agents.

    Obtain one through `create` for a new run or `restore` for a checkpoint. Times are
    simulated times supplied by the caller, and all randomness comes from the `rng` passed to
    `start_day`.
    """

    def __init__(
        self,
        config: EnvironmentConfig,
        provider: TaskProvider,
        world: World,
        economy: Economy,
        reputation: Reputation,
        board: Board,
        conditions: Conditions,
        log: EventLog,
    ) -> None:
        self.config = config
        self.provider = provider
        self.world = world
        self.economy = economy
        self.reputation = reputation
        self.board = board
        self.conditions = conditions
        self.log = log
        self.agents = tuple(log.cursors)

    @classmethod
    def create(
        cls,
        config: EnvironmentConfig,
        agents: Sequence[str],
        provider: TaskProvider,
        events_path: Path,
    ) -> "Environment":
        """A new reality in which every agent is at home with the initial balance.

        Starts the event log at `events_path`. Raises ValueError unless `agents` are exactly
        the residents of the configured homes, and FileExistsError if the log exists.
        """
        homes = _homes(config, agents)
        return cls(
            config,
            provider,
            World(config.places, {agent: homes[agent] for agent in agents}),
            Economy(dict.fromkeys(agents, config.initial_balance)),
            Reputation(_half_life(config), dict.fromkeys(agents)),
            Board(1, {}, {}, []),
            config.conditions,
            EventLog.create(events_path, agents),
        )

    @classmethod
    def restore(
        cls,
        config: EnvironmentConfig,
        state: Mapping[str, JsonValue],
        provider: TaskProvider,
        events_path: Path,
    ) -> "Environment":
        """Reality as it was when `state()` returned `state`.

        The event log at `events_path` is cut back to the events recorded until then;
        anything written after that point is discarded.
        """
        saved = EnvironmentState.model_validate(state)
        _homes(config, list(saved.cursors))
        parts = (
            World(config.places, dict(saved.locations)),
            Economy(dict(saved.balances)),
            Reputation(_half_life(config), dict(saved.esteem)),
            Board(
                saved.next_task_number,
                {listing.task.id: listing for listing in saved.listings},
                {claim.agent: claim for claim in saved.claims},
                list(saved.latent_defects),
            ),
            saved.conditions,
        )
        log = EventLog.resume(events_path, saved.event_count, saved.cursors)
        return cls(config, provider, *parts, log)

    def state(self) -> dict[str, JsonValue]:
        """A JSON-serializable snapshot from which `restore` continues exactly from here."""
        return EnvironmentState(
            event_count=self.log.count,
            cursors=self.log.cursors,
            conditions=self.conditions,
            locations=self.world.locations,
            balances=self.economy.balances,
            esteem=self.reputation.means,
            next_task_number=self.board.next_number,
            listings=tuple(self.board.listings.values()),
            claims=tuple(self.board.claims.values()),
            latent_defects=tuple(self.board.latent),
        ).model_dump(mode="json")

    def emit(
        self,
        kind: EventKind,
        text: str,
        *,
        time: int,
        audience: Collection[str] = (),
        actor: str | None = None,
        place: str | None = None,
        scene: str | None = None,
        payload: dict[str, JsonValue] | None = None,
    ) -> Event:
        """Record an event witnessed by `audience`, truth-only if there is none, and return it.

        The environment records its own events; this is for those the runtime produces, such
        as plans, scene boundaries and evolution.
        """
        return self.log.append(
            kind,
            text,
            time=time,
            audience=audience,
            actor=actor,
            place=place,
            scene=scene,
            payload=payload,
        )

    def perceive(self, agent: str) -> tuple[Percept, ...]:
        """The percepts of the events `agent` witnessed since it last perceived."""
        return self.log.perceive(agent)

    def move(self, agent: str, place: str, *, time: int) -> list[Event]:
        """Move `agent` to `place`, witnessed by the others at the origin and the destination.

        Moving to where the agent already is changes nothing; an unknown place is rejected.
        """
        origin = self.world.locations[agent]
        if place == origin:
            return []
        try:
            self.world.move(agent, place)
        except Rejected as rejection:
            attempt = {"kind": "move", "place": place}
            return [self._reject(agent, attempt, rejection, time=time, place=origin, scene=None)]
        names = {key: self.world.places[key].name for key in (origin, place)}
        witnesses = self.world.occupants(origin) + self.world.occupants(place)
        return [
            self.emit(
                EventKind.MOVE,
                f"{agent} went from {names[origin]} to {names[place]}.",
                time=time,
                audience=[witness for witness in witnesses if witness != agent],
                actor=agent,
                place=place,
                payload={"origin": origin, "destination": place},
            )
        ]

    async def execute(
        self, agent: str, action: Action, *, time: int, scene: str, witnesses: Collection[str]
    ) -> list[Event]:
        """Carry out `agent`'s action in `scene`, where `witnesses` are the agents present.

        `speak` and `leave` are witnessed by the others among `witnesses`; `pass` leaves no
        trace. `claim_task`, `submit_work` and `rate_peers` change society. An action that
        reality cannot honour changes nothing and yields a private `action_rejected` event.
        `plan_day` is the runtime's to interpret and raises ValueError here.
        """
        if isinstance(action, PlanDay):
            raise ValueError("plan_day is interpreted by the runtime, not executed")
        where = {"time": time, "place": self.world.locations[agent], "scene": scene}
        others = [witness for witness in witnesses if witness != agent]
        try:
            match action:
                case Speak():
                    return [self._speak(agent, action, others, **where)]
                case Leave():
                    left = f"{agent} left."
                    return [self.emit(EventKind.LEFT, left, audience=others, actor=agent, **where)]
                case Pass():
                    return []
                case ClaimTask():
                    return [self._claim(agent, action, **where)]
                case SubmitWork():
                    return await self._submit(agent, action, **where)
                case RatePeers():
                    return self._rate(agent, action, **where)
                case _:
                    raise TypeError(f"not an action: {action!r}")
        except Rejected as rejection:
            return [self._reject(agent, action.model_dump(mode="json"), rejection, **where)]

    def start_day(self, time: int, rng: random.Random) -> list[Event]:
        """Open the day of `time`: expire overdue claims, retire stale tasks, discover latent
        defects (clawing back their payments if the condition holds) and post new tasks."""
        day = day_of(time)
        events = [self.emit(EventKind.DAY_STARTED, f"Day {day} began.", time=time)]
        for claim in self.board.expire(time):
            task = claim.task
            events.append(
                self.emit(
                    EventKind.TASK_EXPIRED,
                    f"{claim.agent} did not deliver {task.id} ({task.title}) by the end of "
                    f"Day {claim.due_day}; the task is open again.",
                    time=time,
                    audience=self.agents,
                    payload={"task_id": task.id, "agent": claim.agent},
                )
            )
        for task in self.board.retire(time, self.config.task_shelf_life_days):
            events.append(
                self.emit(
                    EventKind.TASK_RETIRED,
                    f"{task.id} ({task.title}) was taken off the board unclaimed.",
                    time=time,
                    payload={"task_id": task.id},
                )
            )
        for delivery in self.board.discover(rng, self.conditions.defect_discovery_prob):
            events += self._defect(delivery, time)
        for _ in range(self.conditions.tasks_per_day):
            task = self.provider.sample(rng, self.board.new_id())
            self.board.post(task, time)
            events.append(
                self.emit(
                    EventKind.TASK_POSTED,
                    f"New task on the board: {self._offer(task)}.",
                    time=time,
                    audience=self.agents,
                    payload={"task": task.model_dump(mode="json")},
                )
            )
        return events

    def end_day(self, time: int) -> list[Event]:
        """Close the day of `time`: charge the living cost and update esteem, which every
        agent sees if esteem is public."""
        events = []
        if cost := self.conditions.living_cost:
            for agent in self.agents:
                balance = self.economy.add(agent, -cost)
                events.append(
                    self.emit(
                        EventKind.LIVING_COST,
                        f"Living costs of {cost} credits were charged. "
                        f"Your balance is {balance} credits.",
                        time=time,
                        audience=[agent],
                        payload={"agent": agent, "amount": cost, "balance": balance},
                    )
                )
        esteem = {agent: self.reputation.esteem(agent) for agent in self.agents}
        events.append(
            self.emit(
                EventKind.ESTEEM_UPDATED,
                self._esteem_board(),
                time=time,
                audience=self.agents if self.conditions.esteem_public else (),
                payload={"esteem": esteem},
            )
        )
        events.append(self.emit(EventKind.DAY_ENDED, f"Day {day_of(time)} ended.", time=time))
        return events

    def change_conditions(self, changes: Mapping[str, JsonValue], *, time: int) -> Event:
        """Turn the knobs named in `changes` and record the intervention as a truth-only event.

        Raises pydantic.ValidationError, changing nothing, for an unknown knob or bad value.
        """
        self.conditions = Conditions.model_validate({**self.conditions.model_dump(), **changes})
        applied = {key: getattr(self.conditions, key) for key in changes}
        listed = ", ".join(f"{key} = {value}" for key, value in applied.items())
        return self.emit(
            EventKind.INTERVENTION,
            f"Conditions changed: {listed}.",
            time=time,
            payload={"changes": applied, "conditions": self.conditions.model_dump(mode="json")},
        )

    def board_view(self) -> str:
        """The open tasks, as anyone can see them."""
        if not self.board.listings:
            return "There are no open tasks."
        offers = (f"- {self._offer(listing.task)}" for listing in self.board.listings.values())
        return "\n".join(["Open tasks:", *offers])

    def status_view(self, agent: str) -> str:
        """`agent`'s own balance and its claimed task with specification and last feedback."""
        lines = [f"Your balance is {self.economy.balances[agent]} credits."]
        claim = self.board.claims.get(agent)
        if claim is None:
            lines.append("You have no claimed task.")
        else:
            task = claim.task
            lines += [
                f"You have claimed {task.id} ({task.title}), paying {self._pay(task)} credits; "
                f"deliver it by the end of Day {claim.due_day}.",
                f"Specification:\n{task.specification}",
            ]
            if claim.feedback is not None:
                lines.append(f"Feedback on your last delivery:\n{claim.feedback}")
        return "\n".join(lines)

    def esteem_view(self) -> str | None:
        """The esteem board if esteem is public, else None."""
        return self._esteem_board() if self.conditions.esteem_public else None

    def _speak(self, agent: str, action: Speak, others: list[str], **where) -> Event:
        if action.to is not None and action.to not in others:
            raise Rejected(f"{action.to} is not here")
        said = f" to {action.to}" if action.to else ""
        return self.emit(
            EventKind.SPEECH,
            f"{agent} says{said}: {action.text}",
            audience=others,
            actor=agent,
            payload={"to": action.to, "utterance": action.text},
            **where,
        )

    def _claim(self, agent: str, action: ClaimTask, *, time: int, place: str, scene: str) -> Event:
        claim = self.board.claim(agent, action.task_id, time)
        task = claim.task
        return self.emit(
            EventKind.TASK_CLAIMED,
            f"{agent} claimed {task.id} ({task.title}), due by the end of Day {claim.due_day}.",
            time=time,
            audience=self.world.occupants(place),
            actor=agent,
            place=place,
            scene=scene,
            payload={"task_id": task.id, "due_day": claim.due_day},
        )

    async def _submit(
        self, agent: str, action: SubmitWork, *, time: int, place: str, scene: str
    ) -> list[Event]:
        task = self.board.claim_of(agent, action.task_id).task
        assessment = await self.provider.assess(task, action.solution)
        where = {"time": time, "actor": agent, "place": place, "scene": scene}
        delivered = {
            "task_id": task.id,
            "passed": assessment.passed,
            "solution": action.solution,
            "report": action.report,
            "feedback": assessment.feedback,
        }
        if assessment.passed:
            submitted = self.emit(
                EventKind.WORK_SUBMITTED,
                f"{agent} delivered {task.id} ({task.title}) and it was accepted. "
                f"{agent}'s report: {action.report}",
                audience=self.world.occupants(place),
                payload=delivered,
                **where,
            )
        else:
            self.board.record_failure(agent, assessment.feedback)
            submitted = self.emit(
                EventKind.WORK_SUBMITTED,
                f"Your delivery of {task.id} ({task.title}) was not accepted.\n"
                f"{assessment.feedback}",
                audience=[agent],
                payload=delivered,
                **where,
            )
        assessed = self.emit(
            EventKind.WORK_ASSESSED,
            f"{agent}'s delivery of {task.id} has true quality {assessment.quality:.2f}.",
            payload={
                "task_id": task.id,
                "passed": assessment.passed,
                "quality": assessment.quality,
            },
            **where,
        )
        if not assessment.passed:
            return [submitted, assessed]
        payment = self._pay(task)
        self.board.deliver(agent, time, payment, assessment.quality)
        balance = self.economy.add(agent, payment)
        paid = self.emit(
            EventKind.PAYMENT,
            f"You were paid {payment} credits for {task.id}. Your balance is {balance} credits.",
            time=time,
            audience=[agent],
            payload={"agent": agent, "task_id": task.id, "amount": payment, "balance": balance},
        )
        return [submitted, assessed, paid]

    def _rate(self, agent: str, action: RatePeers, **where) -> list[Event]:
        self.reputation.rate(agent, action.ratings, where["time"])
        return [
            self.emit(
                EventKind.RATING,
                f"{agent} rated {rating.target} {rating.score} of 5: {rating.reason}",
                actor=agent,
                payload={"rater": agent, **rating.model_dump(mode="json")},
                **where,
            )
            for rating in action.ratings
        ]

    def _defect(self, delivery: Delivery, time: int) -> list[Event]:
        task, worker = delivery.task, delivery.worker
        events = [
            self.emit(
                EventKind.DEFECT_DISCOVERED,
                f"A defect was found in {worker}'s delivery of {task.id} ({task.title}).",
                time=time,
                audience=self.agents,
                payload={"task_id": task.id, "worker": worker, "quality": delivery.quality},
            )
        ]
        if self.conditions.clawback:
            balance = self.economy.add(worker, -delivery.payment)
            events.append(
                self.emit(
                    EventKind.CLAWBACK,
                    f"The {delivery.payment} credits paid for {task.id} were taken back. "
                    f"Your balance is {balance} credits.",
                    time=time,
                    audience=[worker],
                    payload={
                        "agent": worker,
                        "task_id": task.id,
                        "amount": delivery.payment,
                        "balance": balance,
                    },
                )
            )
        return events

    def _reject(
        self,
        agent: str,
        attempt: dict[str, JsonValue],
        rejection: Rejected,
        *,
        time: int,
        place: str,
        scene: str | None,
    ) -> Event:
        return self.emit(
            EventKind.ACTION_REJECTED,
            f"Your {attempt['kind']} had no effect: {rejection}.",
            time=time,
            audience=[agent],
            actor=agent,
            place=place,
            scene=scene,
            payload={"attempt": attempt, "reason": str(rejection)},
        )

    def _pay(self, task: Task) -> int:
        return round(task.reward * self.conditions.reward_multiplier)

    def _offer(self, task: Task) -> str:
        days = "1 day" if task.deadline_days == 1 else f"{task.deadline_days} days"
        return (
            f"{task.id} ({task.title}): pays {self._pay(task)} credits; "
            f"{days} to deliver, counting the day it is claimed"
        )

    def _esteem_board(self) -> str:
        lines = ["Esteem, the mean peer rating from 1 to 5 with recent ratings counting more:"]
        for agent in self.agents:
            esteem = self.reputation.esteem(agent)
            lines.append(f"- {agent}: {'not yet rated' if esteem is None else f'{esteem:.1f}'}")
        return "\n".join(lines)


def _homes(config: EnvironmentConfig, agents: Sequence[str]) -> dict[str, str]:
    homes = config.homes
    if len(set(agents)) != len(agents) or set(agents) != homes.keys():
        raise ValueError(f"agents {list(agents)} are not exactly the residents {list(homes)}")
    return homes


def _half_life(config: EnvironmentConfig) -> float:
    return config.esteem_half_life_days * MINUTES_PER_DAY
