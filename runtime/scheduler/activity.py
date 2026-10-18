"""Opt-in independent daytime clock. Effects are applied only at completion times.

Wall-clock model/tool latency never chooses the order of equal-time actions. Day-end
checkpoints remain the recovery unit; no running process is serialized.
"""

import asyncio
from dataclasses import dataclass, field

from core.environment import PlaceKind
from core.environment.rejection import AssessmentUnavailable, Rejected
from core.interaction import (
    Decision,
    EventKind,
    MayClaim,
    MayPass,
    MayRunCommand,
    MaySpeak,
    MaySubmit,
    Observation,
    Pass,
    RunCommand,
    Speak,
    SubmitWork,
    clock_of,
    day_of,
    time_at,
)
from core.interaction.actions import Activity
from core.interaction.card import MayActivity
from infrastructure.llm import StructuredOutputError
from runtime.scenes import situations
from runtime.scenes.scene import _announce_draws, _decide, lapse


@dataclass
class Pending:
    agent: str
    decision: Decision
    start: int
    end: int
    place: str
    discussion: str | None = None


@dataclass
class Discussion:
    id: str
    owner: str
    invitee: str
    topic: str
    minutes: int
    accepted: bool = False
    place: str | None = None
    members: list[str] = field(default_factory=list)
    end: int = 0
    speaker: int = 0
    extension: int = 0
    votes: set[str] = field(default_factory=set)
    closed: bool = False


class ActivityClock:
    def __init__(self, simulation):
        self.sim = simulation
        self.env = simulation.env
        self.pending: dict[str, Pending] = {}
        self.discussions: dict[str, Discussion] = {}
        self.grading: dict[str, tuple[int, str, SubmitWork, str, asyncio.Task]] = {}
        self.now = 0
        self.end = 0
        self.planned: set[str] = set()
        self.next_id = 1

    def close_at(self, place: str, now: int) -> int:
        p = self.env.world.places[place]
        closes = p.closing(clock_of(now))
        return min(self.end, time_at(day_of(now), closes)) if closes else self.end

    def can_work(self, agent: str, now: int) -> bool:
        p = self.env.world.places[self.env.world.locations[agent]]
        clock = clock_of(now)
        return (
            p.kind == PlaceKind.WORK
            and p.is_open(clock)
            and ("08:00" <= clock < "12:00" or "14:00" <= clock < "18:00")
            and now + 20
            <= min(
                self.close_at(p.id, now),
                time_at(day_of(now), "12:00" if clock < "12:00" else "18:00"),
            )
        )

    def member_of(self, agent: str) -> Discussion | None:
        return next(
            (d for d in self.discussions.values() if agent in d.members and not d.closed), None
        )

    def allowed(self, agent: str, now: int):
        if agent not in self.planned:
            return (MayActivity(planning=True),)
        place = self.env.world.locations[agent]
        here = self.env.world.occupants(place)
        own = self.member_of(agent)
        if own:
            controls = MayActivity(
                discussion=own.id, extension=bool(own.extension and agent not in own.votes)
            )
            if own.members[own.speaker % len(own.members)] == agent:
                return (
                    controls,
                    MaySpeak(to=tuple(p for p in own.members if p != agent)),
                    MayPass(),
                )
            return (controls, MayPass())
        names = situations.place_names(self.env, agent)
        moves = {
            names[p.id]: p.id
            for p in self.env.world.places.values()
            if p.id != place
            and p.is_open(clock_of(now + 5))
            and (p.kind != PlaceKind.HOME or p.id == self.env.config.homes[agent])
        }
        other = tuple(p for p in self.env.agents if p != agent)
        replies = tuple(
            d.id
            for d in self.discussions.values()
            if not d.closed and not d.members and d.invitee == agent and not d.accepted
        )
        starts = tuple(
            d.id
            for d in self.discussions.values()
            if not d.closed and not d.members and d.accepted and agent in (d.owner, d.invitee)
        )
        joins = tuple(
            d.id
            for d in self.discussions.values()
            if not d.closed and d.members and d.place == place and now + 5 < d.end
        )
        allowed = [
            MayActivity(
                moves=moves,
                people=other,
                nearby=tuple(p for p in here if p != agent),
                replies=replies,
                starts=starts,
                joins=joins,
            ),
            MayPass(),
        ]
        if len(here) > 1:
            allowed.append(MaySpeak(to=tuple(p for p in here if p != agent)))
        # The notice board can be read/contacted outside working hours from any location.
        claim = self.env.board.claim_of(agent)
        if claim is None:
            tasks = [listing.task for listing in self.env.board.listings.values()]
            offer = self.env.board.offers.get(agent)
            allowed.append(
                MayClaim(
                    alone=tuple(t.id for t in tasks if t.worker_count == 1),
                    together=tuple(t.id for t in tasks if t.worker_count == 2),
                    shared=tuple(t.id for t in tasks if t.worker_count == 2 and len(t.parts) == 1),
                    partners=other if self.env.conditions.partner_choice else None,
                    standing=None if offer is None else (offer.task_id, offer.partner),
                )
            )
        elif claim.task.id not in self.grading:
            parts = tuple(i for i in range(1, len(claim.task.parts) + 1) if not claim.delivery(i))
            if parts:
                if self.can_work(agent, now):
                    allowed.append(MayRunCommand(task_id=claim.task.id, parts=parts))
                # Submitting transfers an existing patch; it is not another editing tool.
                allowed.append(MaySubmit(task_id=claim.task.id, parts=parts))
        return tuple(allowed)

    def observation(self, agent: str, now: int) -> Observation:
        own = self.member_of(agent)
        topic = ""
        if own:
            topic = (
                f"Discussion {own.id}: {own.topic}. Participants: {', '.join(own.members)}. "
                f"Ends at {clock_of(own.end)}. Speaker: "
                f"{own.members[own.speaker % len(own.members)]}. "
                f"Proposed extra minutes: {own.extension}."
            )
        invitations = [
            f"{d.id}: {d.owner} invites {d.invitee} to discuss {d.topic} "
            f"for {d.minutes} minutes; accepted={d.accepted}."
            for d in self.discussions.values()
            if not d.closed and not d.members and agent in (d.owner, d.invitee)
        ]
        joins = [
            f"{d.id}: {d.topic}, participants {', '.join(d.members)}"
            for d in self.discussions.values()
            if d.members and not d.closed and d.place == self.env.world.locations[agent]
        ]
        situation = (
            f"It is {clock_of(now)}. Current goal: {self.sim.goals.get(agent, 'Not yet set')}.\n"
            "Choose your next action. Simple actions take 5 minutes; a terminal action takes "
            "20 minutes and permits one bounded command. Change your current goal in the reply "
            "if needed. A command cannot cross noon or 18:00; all activities end at 22:00. "
            "Use WORKTREE when handing in existing edits. Invitations do not reserve anyone; "
            "meet in the same open place and start only when everyone is free.\n"
            + topic
            + "\n"
            + "\n".join(invitations + joins)
            + "\n"
            + self.env.board_view(agent)
            + "\n"
            + self.env.status_view(agent, include_evidence=False)
        )
        return Observation(
            agent=agent,
            time=now,
            place=self.env.world.locations[agent],
            scene=f"day-{day_of(now):04d}/activities",
            setting=self.setting(agent),
            situation=situation,
            percepts=self.env.perceive(agent),
            evidence=self.env.work_evidence(agent),
            allowed=self.allowed(agent, now),
            places=situations.place_names(self.env, agent),
            goal_updates=agent in self.planned,
        )

    def setting(self, agent):
        places = "\n".join(
            f"{p.name}: {p.kind}, hours {p.spans()}" for p in self.env.world.places.values()
        )
        return (
            self.env.config.setting.backdrop
            + "\n"
            + places
            + "\n"
            + self.env.rules_view()
            + (
                "\nEach morning at 07:00 the clerk replaces completed jobs before you "
                "choose a short current goal. You decide again after every action. Between 07:00 "
                "and 08:00, and at lunch 12:00–14:00, you may read notices, take jobs, move or "
                "talk, but not work. Conversations are voluntary; merely being nearby "
                "does not join you."
            )
        )

    def emit(self, kind, text, agent, now, **payload):
        return self.env.emit(
            kind,
            text,
            time=now,
            actor=agent,
            place=self.env.world.locations[agent],
            audience=[agent],
            payload=payload,
        )

    async def decide(self, agents, now):
        observations = [self.observation(a, now) for a in agents]
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(_decide(self.sim.agents[o.agent], o, True)) for o in observations
            ]
        for agent, task in zip(agents, tasks, strict=True):
            decision = task.result()
            failed = isinstance(decision, StructuredOutputError)
            if failed:
                lapse(self.env, agent, decision, time=now)
                decision = Decision(thought="", action=Pass())
                self.planned.add(agent)
            if decision.goal is not None:
                self.goal(agent, decision.goal, now)
            action = decision.action
            duration = 20 if isinstance(action, RunCommand) else 5
            own = self.member_of(agent)
            self.pending[agent] = Pending(
                agent,
                decision,
                now,
                now + duration,
                self.env.world.locations[agent],
                own.id if own else None,
            )
            if not failed:
                self.emit(
                    EventKind.DECISION,
                    f"{agent} chose {action.kind}.",
                    agent,
                    now,
                    thought=decision.thought,
                    action=action.model_dump(mode="json"),
                )
            self.emit(
                EventKind.ACTION_STARTED,
                f"{agent} began {action.kind}; finishes at {clock_of(now + duration)}.",
                agent,
                now,
                action=action.model_dump(mode="json"),
                start=now,
                end=now + duration,
                discussion=own.id if own else None,
            )

    def goal(self, agent, text, now):
        self.sim.goals[agent] = text[:600]
        self.emit(
            EventKind.GOAL_UPDATED, f"Current goal: {text[:600]}", agent, now, goal=text[:600]
        )

    def discuss_event(self, d, text, now):
        audience = list(dict.fromkeys([d.owner, d.invitee, *d.members]))
        self.env.emit(
            EventKind.DISCUSSION,
            text,
            time=now,
            audience=audience,
            place=d.place,
            payload={
                "discussion": d.id,
                "members": list(d.members),
                "end": d.end,
                "closed": d.closed,
                "topic": d.topic,
            },
        )

    def stop(self, d, now):
        d.closed = True
        self.discuss_event(d, f"Discussion {d.id} ended.", now)
        d.members = []

    def control(self, agent, action, now):
        op = action.operation
        if op == "goal":
            self.goal(agent, action.topic, now)
            self.planned.add(agent)
            return
        if op == "move":
            if action.target not in self.env.world.places:
                raise Rejected("That destination is unavailable.")
            self.env.move(agent, action.target, time=now)
            return
        if op == "invite":
            if action.target == agent or action.target not in self.env.agents:
                raise Rejected("Choose another resident.")
            if (
                not action.remote
                and self.env.world.locations[action.target] != self.env.world.locations[agent]
            ):
                raise Rejected("That resident has moved away.")
            d = Discussion(
                f"discussion-{day_of(now)}-{self.next_id}",
                agent,
                action.target,
                action.topic,
                action.minutes,
            )
            self.next_id += 1
            self.discussions[d.id] = d
            self.discuss_event(
                d,
                f"{agent} invites {action.target}: {action.topic}; "
                f"suggested duration {action.minutes} minutes ({d.id}).",
                now,
            )
            return
        d = self.discussions.get(action.target)
        if d is None or d.closed:
            raise Rejected("That discussion is no longer available.")
        if op in ("accept", "decline"):
            if agent != d.invitee or d.members:
                raise Rejected("That invitation cannot be answered now.")
            d.accepted = op == "accept"
            d.closed = op == "decline"
            self.discuss_event(d, f"{agent} {op}s {d.id}; nobody is reserved.", now)
        elif op == "start":
            if agent not in (d.owner, d.invitee) or not d.accepted or d.members:
                raise Rejected("Both residents must agree before starting.")
            members = [d.owner, d.invitee]
            place = self.env.world.locations[agent]
            if any(
                p in self.pending or self.member_of(p) or self.env.world.locations[p] != place
                for p in members
            ):
                raise Rejected("Both residents must be free and in the same place now.")
            if not self.env.world.places[place].is_open(clock_of(now)):
                raise Rejected("This place is closed.")
            end = min(now + d.minutes, self.close_at(place, now))
            if end < now + 5:
                raise Rejected("There is not enough time before closing.")
            d.members, d.place, d.end = members, place, end
            self.discuss_event(d, f"Discussion {d.id} begins until {clock_of(end)}.", now)
            for p in members:
                self.sim._met[p].update(set(members) - {p})
        elif op == "join":
            if not d.members or self.member_of(agent) or d.place != self.env.world.locations[agent]:
                raise Rejected("Join only a discussion taking place here.")
            if any(p in self.pending for p in d.members) or now + 5 > d.end:
                raise Rejected("Wait for a free turn boundary to join.")
            d.members.append(agent)
            # A new member has not agreed to an earlier extension proposal.
            self.discuss_event(d, f"{agent} joined {d.id}.", now)
            for p in d.members:
                self.sim._met[p].update(set(d.members) - {p})
        elif agent not in d.members:
            raise Rejected("You are not taking part in this discussion.")
        elif op == "exit":
            d.members.remove(agent)
            d.votes.discard(agent)
            self.discuss_event(d, f"{agent} left {d.id}.", now)
            if len(d.members) < 2:
                self.stop(d, now)
        elif op in ("extend", "agree"):
            if op == "extend":
                d.extension, d.votes = action.minutes, {agent}
            else:
                if not d.extension:
                    raise Rejected("No extra time has been proposed.")
                d.votes.add(agent)
            if set(d.members) <= d.votes:
                d.end = min(d.end + d.extension, self.close_at(d.place, now - 1))
                d.extension, d.votes = 0, set()
            self.discuss_event(
                d,
                f"{agent} responded about extra time for {d.id}; agreed end {clock_of(d.end)}.",
                now,
            )

    async def submit(self, agent, action, now, place):
        claim = self.env.board.work_on(agent, action.task_id, action.part)
        if claim.task.id in self.grading:
            raise Rejected("The client is already checking this job.")
        if action.solution.strip() != "WORKTREE":
            raise Rejected("Hand in WORKTREE; make code edits during a work action first.")
        provider = self.env.providers[claim.task.trade]
        part = claim.task.parts[action.part - 1]
        patch = await provider.prepare_submission(part, agent, claim.task.id, "WORKTREE")
        frozen = action.model_copy(update={"solution": patch})

        async def assess():
            try:
                return await provider.assess(part, patch)
            except AssessmentUnavailable as exc:
                return exc

        due = min(self.end, now + self.sim.config.grading_minutes)
        self.grading[claim.task.id] = (due, agent, frozen, place, asyncio.create_task(assess()))
        self.emit(
            EventKind.SUBMISSION_PENDING,
            f"The client received your patch; feedback is due by {clock_of(due)}.",
            agent,
            now,
            task_id=claim.task.id,
            feedback_at=due,
        )

    async def complete(self, now):
        finished = [p for p in self.pending.values() if p.end == now]
        for p in finished:
            del self.pending[p.agent]
        # Apply exit/consent changes before any discussion speech at the same boundary.
        self.sim.rng.shuffle(finished)

        def phase(p):
            action = p.decision.action
            if isinstance(action, Activity):
                if action.operation in ("start", "join"):
                    return 2  # all arrivals/departures finish before the availability check
                if p.discussion:
                    return 0
            return 1

        finished.sort(key=phase)
        _announce_draws(self.env, [(None, p.agent, p.decision) for p in finished], now)
        for p in finished:
            action, agent = p.decision.action, p.agent
            try:
                if isinstance(action, Activity):
                    self.control(agent, action, now)
                elif isinstance(action, SubmitWork):
                    await self.submit(agent, action, now, p.place)
                else:
                    if p.discussion:
                        d = self.discussions[p.discussion]
                        if d.closed or agent not in d.members:
                            continue
                        witnesses = (
                            self.env.world.occupants(p.place)
                            if isinstance(action, Speak) and not action.private
                            else list(d.members)
                        )
                    else:
                        witnesses = self.env.world.occupants(p.place)
                    emitted = await self.env.execute(
                        agent,
                        action,
                        time=now,
                        scene=f"day-{day_of(now):04d}/activities",
                        witnesses=witnesses,
                    )
                    if isinstance(action, Speak) and any(
                        e.kind == EventKind.SPEECH for e in emitted
                    ):
                        heard = witnesses if action.to is None else [action.to]
                        for person in heard:
                            if person != agent:
                                self.sim._met[agent].add(person)
                                self.sim._met[person].add(agent)
            except Rejected as exc:
                self.env._reject(
                    agent,
                    action.model_dump(mode="json"),
                    exc,
                    time=now,
                    place=self.env.world.locations[agent],
                    scene=f"day-{day_of(now):04d}/activities",
                )
            finally:
                self.emit(
                    EventKind.ACTION_COMPLETED,
                    f"{agent} finished {action.kind}.",
                    agent,
                    now,
                    start=p.start,
                    end=now,
                    action=action.model_dump(mode="json"),
                )
        self.env.pair_applicants(now, self.sim.rng)
        for ident in {p.discussion for p in finished if p.discussion}:
            d = self.discussions[ident]
            d.speaker += 1
        for job, (due, agent, action, place, future) in list(self.grading.items()):
            if due <= now:
                assessment = await future
                await self.env._submit(
                    agent,
                    action,
                    time=now,
                    place=place,
                    scene=f"day-{day_of(now):04d}/activities",
                    prepared=(action.solution, assessment),
                )
                del self.grading[job]

    def boundary(self, now):
        for d in self.discussions.values():
            if (
                d.members
                and not d.closed
                and (now >= d.end or not self.env.world.places[d.place].is_open(clock_of(now)))
            ):
                self.stop(d, now)
        # Closing is enforced even if someone planned to stay. Home is always available.
        for agent, place in list(self.env.world.locations.items()):
            p = self.env.world.places[place]
            if p.kind != PlaceKind.HOME and not p.is_open(clock_of(now)):
                if now == self.end:
                    self.env.move(agent, self.env.config.homes[agent], time=now, closing=True)
                elif agent not in self.pending:
                    action = Activity(operation="move", target=self.env.config.homes[agent])
                    self.pending[agent] = Pending(
                        agent,
                        Decision(thought="The place closed.", action=action),
                        now,
                        now + 5,
                        place,
                    )
                    self.emit(
                        EventKind.ACTION_STARTED,
                        "The place closed; returning home.",
                        agent,
                        now,
                        start=now,
                        end=now + 5,
                        action=action.model_dump(mode="json"),
                    )

    async def run(self, start):
        self.now, self.end = start, self.sim.config.calendar.end(day_of(start))
        boundaries = {
            time_at(day_of(start), t) for t in ("08:00", "12:00", "14:00", "18:00", "22:00")
        }
        for p in self.env.world.places.values():
            for opens, closes in p.spans():
                boundaries.update(time_at(day_of(start), t) for t in (opens, closes))
        changes = []
        while len(self.sim.queue) and self.sim.queue.state()[0].time <= self.end:
            changes.append(self.sim.queue.pop())
        boundaries.update(t.time for t in changes)
        try:
            while True:
                now = self.now
                await self.complete(now)
                for trigger in list(changes):
                    if trigger.time == now:
                        self.sim._intervene(now, trigger.payload)
                        changes.remove(trigger)
                self.boundary(now)
                if now == self.end:
                    break
                idle = [a for a in self.sim.agents if a not in self.pending]
                # Members begin together only at a shared turn boundary.
                idle = [
                    a
                    for a in idle
                    if not (d := self.member_of(a)) or not any(p in self.pending for p in d.members)
                ]
                if now + 5 <= self.end:
                    await self.decide(idle, now)
                self.sim._bound_lapses()
                times = [p.end for p in self.pending.values()]
                times += [v[0] for v in self.grading.values()]
                times += [t for t in boundaries if t > now]
                times += [
                    d.end
                    for d in self.discussions.values()
                    if d.members and not d.closed and d.end > now
                ]
                self.now = min(times)
            for d in self.discussions.values():
                if not d.closed:
                    self.stop(d, self.end)
        finally:
            for *_, future in self.grading.values():
                future.cancel()
            await asyncio.gather(*(v[-1] for v in self.grading.values()), return_exceptions=True)
