"""Work: the agents at a work place take jobs, try and hand in code, talk, and go home when
they choose, hour by hour."""

from collections.abc import Mapping, Sequence

from core.environment import DELIVERY, EXAMPLES, Environment
from core.interaction import (
    Allowance,
    Decision,
    EventKind,
    Leave,
    MayCheck,
    MayClaim,
    MayDismiss,
    MayGive,
    MayHire,
    MayLeave,
    MayPass,
    MaySpeak,
    MaySubmit,
    Pass,
)
from runtime.scenes import situations
from runtime.scenes.scene import Scene, careers


class WorkSession(Scene):
    """The agents at a work place from `start` until `until`, when the place closes or the
    part of the day ends, in at most `rounds` rounds spread evenly over that time; in each,
    every agent still present decides at once, told that what it does takes it to the next
    round, or to `until` in the last. One who goes home is no longer present, and a round in
    which everyone still present carries on quietly, or after which nobody is left, ends the
    session: those there work on until `until`. `closes` says whether `until` is the place's
    closing time, and `posting` when new notices next go up, if known."""

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
        posting: int | None = None,
    ) -> None:
        super().__init__(env, id, place, participants, start, (until - start) // rounds)
        self.rounds = rounds
        self.until = until
        self.closes = closes
        self.posting = posting
        self.present = list(participants)

    def ask(self) -> list[str]:
        return list(self.present)

    @property
    def following(self) -> int:
        """When what an agent does in the next round takes it to: the round after, or `until`
        in the last."""
        return self.until if self.turns + 1 >= self.rounds else self.next_time + self.step

    def allowed(self, agent: str) -> tuple[Allowance, ...]:
        """Someone working on no job may take one from the notices it faces here (the board,
        or its firm's job sheet), if any is there, a job for two with a neighbour, or with one
        of the firm's people on its sheet, but in the last moment of the day at which work can
        be handed in none to be done by the end of that day (`situations.last_moment`), as the
        board says; someone working on one may hand in the parts not yet in, and try them
        where the job's trade gives something to try against. A foreman at its firm may take
        on those who asked for its place while it has one, and dismiss its staff; anyone may
        ask for a place or give notice (`careers`). Anyone may talk to and hand money to the
        others here, go home for the rest of this part of the day, or carry on quietly."""
        env, allowed, firms = self.env, [], self.env.firms
        claim = env.board.claim_of(agent)
        firm = self.place if self.place in firms.establishments else None
        if claim is None:
            late = situations.last_moment(env, self.following, self.until)
            tasks = env.notices_for(agent, self.place, late=late)
            alone = tuple(task.id for task in tasks if len(task.parts) == 1)
            together = tuple(task.id for task in tasks if len(task.parts) > 1)
            people = firms.people(firm) if firm is not None else env.agents
            neighbours = tuple(other for other in people if other != agent)
            partners = neighbours if env.conditions.partner_choice else None
            if alone or (together and partners != ()):
                allowed.append(MayClaim(alone=alone, together=together, partners=partners))
        else:
            task = claim.task
            parts = tuple(n for n in range(1, len(task.parts) + 1) if claim.delivery(n) is None)
            drafts = tuple(
                n for n in parts if (trial := claim.last_trial(agent, n)) and trial.solution
            )
            working = {
                "task_id": task.id,
                "parts": parts,
                "delivery": DELIVERY[task.trade],
                "drafts": drafts,
            }
            if task.trade in EXAMPLES:
                allowed.append(MayCheck(**working))
            allowed.append(MaySubmit(**working))
        if firm is not None and firms.foreman_of(firm) == agent:
            if (applicants := firms.applicants(firm)) and firms.vacancies(firm) > 0:
                allowed.append(MayHire(applicants=tuple(applicants)))
            if staff := firms.staff[firm]:
                allowed.append(MayDismiss(staff=tuple(staff)))
        allowed += careers(env, agent)
        if others := tuple(other for other in self.present if other != agent):
            units = env.config.setting.currency.units
            allowed += [MaySpeak(to=others), MayGive(to=others, units=units)]
        return (*allowed, MayLeave(), MayPass())

    def situation(self, agent: str) -> str:
        others = [other for other in self.present if other != agent]
        return situations.work(
            self.env,
            self.place,
            others,
            agent,
            now=self.next_time,
            following=self.following,
            until=self.until,
            closes=self.closes,
            posting=self.posting,
        )

    def shown(self) -> tuple[EventKind, ...]:
        """The board, and one's job (which the desk at night told)."""
        return (EventKind.TASK_POSTED, EventKind.DESK)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        await self.env.execute(
            agent, decision.action, time=time, scene=self.id, witnesses=self.present
        )
        if isinstance(decision.action, Leave):
            self.present.remove(agent)

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        stayed = [decisions[agent] for agent in self.present if agent in decisions]
        return (
            not self.present
            or self.turns >= self.rounds
            or all(isinstance(decision.action, Pass) for decision in stayed)
        )
