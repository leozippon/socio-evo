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
    MayGive,
    MayLeave,
    MayPass,
    MaySpeak,
    MaySubmit,
    Pass,
)
from runtime.scenes import situations
from runtime.scenes.scene import Scene


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

    def allowed(self, agent: str) -> tuple[Allowance, ...]:
        """Someone working on no job may take one from the board, if any is there; someone
        working on one may hand in the parts not yet in, and try them where the job's trade
        gives something to try against. Anyone may talk to and hand money to the others here,
        go home for the rest of this part of the day, or carry on quietly."""
        env, allowed = self.env, []
        claim = env.board.claim_of(agent)
        if claim is None:
            tasks = [listing.task for listing in env.board.listings.values()]
            alone = tuple(task.id for task in tasks if len(task.parts) == 1)
            together = tuple(task.id for task in tasks if len(task.parts) > 1)
            neighbours = tuple(other for other in env.agents if other != agent)
            partners = neighbours if env.conditions.partner_choice else None
            if alone or (together and partners != ()):
                allowed.append(MayClaim(alone=alone, together=together, partners=partners))
        else:
            task = claim.task
            parts = tuple(n for n in range(1, len(task.parts) + 1) if claim.delivery(n) is None)
            working = {"task_id": task.id, "parts": parts, "delivery": DELIVERY[task.trade]}
            if task.trade in EXAMPLES:
                allowed.append(MayCheck(**working))
            allowed.append(MaySubmit(**working))
        if others := tuple(other for other in self.present if other != agent):
            units = env.config.setting.currency.units
            allowed += [MaySpeak(to=others), MayGive(to=others, units=units)]
        return (*allowed, MayLeave(), MayPass())

    def situation(self, agent: str) -> str:
        others = [other for other in self.present if other != agent]
        last = self.turns + 1 >= self.rounds
        return situations.work(
            self.env,
            self.place,
            others,
            agent,
            now=self.next_time,
            following=self.until if last else self.next_time + self.step,
            until=self.until,
            closes=self.closes,
            posting=self.posting,
        )

    def shown(self) -> tuple[EventKind, ...]:
        """The board."""
        return (EventKind.TASK_POSTED,)

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
