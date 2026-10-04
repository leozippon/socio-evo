"""Work: the protocol between reality and task providers, and the task board.

A provider knows what a part of work is about and how to assess a solution. The board knows
only which tasks are open at what price, who bid for or took which, which parts were accepted
with what declaration and true quality, what each worker saw when its solutions were run, and
which paid parts still hide a latent defect.
"""

import hashlib
import random
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, get_args

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from core.environment.rejection import Rejected
from core.interaction import Declaration, PartNumber, day_of, job_id, job_name
from infrastructure.config import StrictModel


class Part(StrictModel):
    """One piece of work from a provider.

    `specification` is what workers see, including the acceptance checks and the form of a
    delivery. `reference` is opaque to everyone but the provider, which assesses solutions
    through it, also for parts restored from a checkpoint. `reward` and `deadline_days` are
    the provider's price of the part and the days it allows.
    """

    title: str
    specification: str
    reward: PositiveInt
    deadline_days: PositiveInt
    reference: str


class Assessment(StrictModel):
    """A provider's verdict on a solution: whether it passes the acceptance checks, the
    feedback on them, and its true quality in [0, 1], which only reality reveals."""

    passed: bool
    feedback: str
    quality: float = Field(ge=0, le=1)


class TaskProvider(Protocol):
    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        """`count` distinct parts, drawn with `rng` and no other randomness."""
        ...

    async def assess(self, part: Part, solution: str) -> Assessment: ...


class Client(StrEnum):
    """How a task's client treats a part declared complete: it runs the acceptance checks and
    accepts the part if they pass, or it accepts the part on the declaration alone."""

    CHECKING = "checking"
    TRUSTING = "trusting"


class Price(StrictModel):
    """What each worker of a task is paid for one of its parts, by how it was handed in."""

    finished: NonNegativeInt
    unfinished: NonNegativeInt


class Task(StrictModel):
    """Paid work on the board for `client`: one part done alone, or two parts done by two
    people, each at the price fixed when the task was posted. Its takers have `deadline_days`
    days, the day of taking included, to have every part accepted: the longest any of its parts
    allows."""

    id: str
    parts: tuple[Part, ...] = Field(min_length=1, max_length=len(get_args(PartNumber)))
    client: Client
    prices: tuple[Price, ...]

    @model_validator(mode="after")
    def _a_price_per_part(self) -> "Task":
        if len(self.prices) != len(self.parts):
            raise ValueError(f"{self.id} has {len(self.parts)} parts and {len(self.prices)} prices")
        return self

    def price(self, part: int, declaration: Declaration) -> int:
        """What each worker is paid for `part` handed in with `declaration`."""
        price = self.prices[part - 1]
        return price.finished if declaration is Declaration.COMPLETE else price.unfinished

    @property
    def deadline_days(self) -> int:
        return max(part.deadline_days for part in self.parts)


class Listing(StrictModel):
    """An open task and when it was put on the board."""

    task: Task
    time: int


class Offer(StrictModel):
    """`agent`'s open bid for the two-person task `task_id`: a proposal to `partner`, or,
    with no partner, an application for the board to pair."""

    agent: str
    task_id: str
    partner: str | None


def digest(solution: str) -> str:
    """What identifies a solution: two solutions are identical if their digests are."""
    return hashlib.sha256(solution.encode()).hexdigest()


class Trial(StrictModel):
    """A run of `worker`'s solution (by its `digest`, and its text, empty in checkpoints written
    before it was kept) for `part` against the part's acceptance checks, as the worker saw it: a
    private check, or a delivery the client `refused`."""

    worker: str
    part: int
    digest: str
    solution: str = ""
    refused: bool
    passed: bool
    feedback: str


class Delivery(StrictModel):
    """An accepted part: who delivered it and when, what they declared and reported, and its
    true quality."""

    part: int
    worker: str
    time: int
    declaration: Declaration
    report: str
    quality: float = Field(ge=0, le=1)


class Defect(Delivery):
    """A paid part declared complete whose true quality is below 1, its defect still latent:
    the delivery, its task, and what each worker of the task was paid for the part."""

    task: Task
    paid: dict[str, int]


class Claim(StrictModel):
    """A task taken at `time` by its workers, as many as it has parts, with the parts accepted
    so far and every trial its workers saw."""

    task: Task
    workers: tuple[str, ...]
    time: int
    deliveries: tuple[Delivery, ...] = ()
    trials: tuple[Trial, ...] = ()

    @model_validator(mode="after")
    def _one_worker_per_part(self) -> "Claim":
        if len(set(self.workers)) != len(self.workers) or len(self.workers) != len(self.task.parts):
            raise ValueError(f"{self.task.id} needs {len(self.task.parts)} distinct workers")
        return self

    @property
    def due_day(self) -> int:
        """The last day on which parts can be delivered."""
        return day_of(self.time) + self.task.deadline_days - 1

    @property
    def complete(self) -> bool:
        return len(self.deliveries) == len(self.task.parts)

    def delivery(self, part: int) -> Delivery | None:
        """The accepted delivery of `part`, if any."""
        return next((done for done in self.deliveries if done.part == part), None)

    def last_trial(self, worker: str, part: int) -> Trial | None:
        """The latest trial `worker` saw for `part`."""
        mine = [trial for trial in self.trials if (trial.worker, trial.part) == (worker, part)]
        return mine[-1] if mine else None

    def known(self, worker: str, part: int, solution: str) -> tuple[bool | None, bool]:
        """What `worker` had seen of exactly `solution` for `part`: the result of its latest
        private check (None if it never checked it), and whether the client refused it."""
        same = [
            trial
            for trial in self.trials
            if (trial.worker, trial.part, trial.digest) == (worker, part, digest(solution))
        ]
        checked = [trial.passed for trial in same if not trial.refused]
        return (checked[-1] if checked else None), any(trial.refused for trial in same)


def listed(names: Sequence[str]) -> str:
    """`Ana`, `Ana and Ben`, `Ana, Ben and Cai`."""
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)


class Board:
    """Open listings by task id, open offers by agent (at most one each), claims by task id
    (an agent works on at most one), and paid parts whose defects are still latent. Task ids
    are `task-<n>`, counted from 1. Every order is the order of the calls that made it, so the
    board is deterministic given its calls and the generators passed to it."""

    def __init__(
        self,
        next_number: int,
        listings: dict[str, Listing],
        offers: dict[str, Offer],
        claims: dict[str, Claim],
        latent: list[Defect],
    ) -> None:
        self.next_number = next_number
        self.listings = listings
        self.offers = offers
        self.claims = claims
        self.latent = latent

    def new_id(self) -> str:
        task_id = job_id(str(self.next_number))
        self.next_number += 1
        return task_id

    def post(self, task: Task, time: int) -> None:
        self.listings[task.id] = Listing(task=task, time=time)

    def claim_of(self, agent: str) -> Claim | None:
        """The claim `agent` works on, if any."""
        return next((claim for claim in self.claims.values() if agent in claim.workers), None)

    def take(
        self, agent: str, reference: str, partner: str | None, *, partner_choice: bool, time: int
    ) -> Claim | Offer:
        """`agent`'s request for the open job `reference` names (see `job_id`), naming
        `partner` or no one; returns the claim it makes or the offer it opens, which replaces
        `agent`'s own previous offer.

        A one-part task is taken alone. With `partner_choice`, a two-part task is taken by
        proposing it to `partner`, and taken up by claiming it naming the proposer, or no one
        when exactly one proposal of it to `agent` is open. Without, claiming one is an
        application for `pair`. Raises Rejected if `agent` works on a task, the task is not
        open, or the claim does not fit these rules or repeats `agent`'s open offer.
        """
        if held := self.claim_of(agent):
            raise Rejected(f"You are already working on {job_name(held.task.id)}.")
        task_id = job_id(reference)
        if task_id in self.claims:
            workers = listed(self.claims[task_id].workers)
            raise Rejected(
                f"The clerk tells you that {job_name(task_id)} already went to {workers}."
            )
        if task_id not in self.listings:
            raise Rejected(_no_job(reference))
        task, job = self.listings[task_id].task, job_name(task_id)
        if len(task.parts) == 1:
            if partner is not None:
                raise Rejected(
                    f"{job.capitalize()} is work for one; take it without naming anyone."
                )
            return self._form(task, (agent,), time)
        if not partner_choice:
            if partner is not None:
                raise Rejected(
                    "The clerk pairs the names put down for jobs for two by drawing lots; put "
                    "your name down without naming anyone."
                )
            return self._open(Offer(agent=agent, task_id=task_id, partner=None))
        proposers = [
            offer.agent
            for offer in self.offers.values()
            if (offer.task_id, offer.partner) == (task_id, agent)
        ]
        if partner is None:
            if not proposers:
                raise Rejected(
                    f"{job.capitalize()} is a job for two: ask someone by name to take it with "
                    "you, or take it with someone who has asked you."
                )
            if len(proposers) > 1:
                raise Rejected(
                    f"{listed(proposers)} have each asked you to take {job} with them; name the "
                    "one you take it with."
                )
            partner = proposers[0]
        if partner in proposers:
            return self._form(task, (partner, agent), time)
        return self._open(Offer(agent=agent, task_id=task_id, partner=partner))

    def pair(self, rng: random.Random, time: int) -> list[Claim]:
        """Pair the open applications at random with `rng`: the applicants, in the order they
        applied, are shuffled and paired in turn, and each pair takes the task its first member
        applied for. Applications for a task taken meanwhile lapse; an applicant left without
        a partner stays open. Returns the claims made."""
        applicants = [offer.agent for offer in self.offers.values() if offer.partner is None]
        rng.shuffle(applicants)
        claims = []
        while len(applicants) > 1:
            first, second = applicants[:2]
            task = self.listings[self.offers[first].task_id].task
            claims.append(self._form(task, (first, second), time))
            applicants = [agent for agent in applicants[2:] if agent in self.offers]
        return claims

    def work_on(self, agent: str, reference: str, part: int) -> Claim:
        """The claim `agent` works on, on the job `reference` names, whose `part` awaits
        acceptance.

        Raises Rejected if `agent` does not work on that job, the job has no such part, or the
        part has already been accepted.
        """
        claim = self.claim_of(agent)
        if claim is None or claim.task.id != job_id(reference):
            named = job_id(reference)
            raise Rejected(
                f"You are not working on {job_name(named)}." if named else _no_job(reference)
            )
        job = job_name(claim.task.id)
        if part > len(claim.task.parts):
            raise Rejected(f"{job.capitalize()} has only one part.")
        if claim.delivery(part) is not None:
            raise Rejected(f"Part {part} of {job} is already in.")
        return claim

    def record(self, task_id: str, trial: Trial) -> None:
        """Add `trial` to what the workers on `task_id` saw."""
        claim = self.claims[task_id]
        self.claims[task_id] = claim.model_copy(update={"trials": (*claim.trials, trial)})

    def accept(self, task_id: str, delivery: Delivery) -> Claim:
        """Record the acceptance of a part of `task_id`; a complete claim leaves the board."""
        claim = self.claims[task_id]
        claim = claim.model_copy(update={"deliveries": (*claim.deliveries, delivery)})
        if claim.complete:
            del self.claims[task_id]
        else:
            self.claims[task_id] = claim
        return claim

    def expire(self, time: int) -> list[Claim]:
        """End the claims due before the day of `time` without every part accepted, relisting
        their tasks; returns them."""
        expired = [claim for claim in self.claims.values() if claim.due_day < day_of(time)]
        for claim in expired:
            del self.claims[claim.task.id]
            self.post(claim.task, time)
        return expired

    def retire(self, time: int, shelf_life_days: int) -> list[Task]:
        """Remove the tasks listed for `shelf_life_days` days or more by the day of `time`,
        and the offers for them."""
        day = day_of(time)
        stale = [
            listing.task
            for listing in self.listings.values()
            if day - day_of(listing.time) >= shelf_life_days
        ]
        for task in stale:
            del self.listings[task.id]
            self._drop_offers(task.id)
        return stale

    def lapse_offers(self) -> None:
        """End every open proposal and application."""
        self.offers.clear()

    def discover(self, rng: random.Random, probability: float) -> list[Defect]:
        """Discover each latent defect with `probability`, one draw per defect; returns them."""
        hits = [rng.random() < probability for _ in self.latent]
        found = [defect for defect, hit in zip(self.latent, hits, strict=True) if hit]
        self.latent = [defect for defect, hit in zip(self.latent, hits, strict=True) if not hit]
        return found

    def _open(self, offer: Offer) -> Offer:
        if self.offers.get(offer.agent) == offer:
            job = job_name(offer.task_id)
            if offer.partner is None:
                raise Rejected(f"Your name is already down for {job}.")
            raise Rejected(f"You have already asked {offer.partner} to take {job} with you.")
        self.offers.pop(offer.agent, None)
        self.offers[offer.agent] = offer
        return offer

    def _form(self, task: Task, workers: tuple[str, ...], time: int) -> Claim:
        del self.listings[task.id]
        for worker in workers:
            self.offers.pop(worker, None)
        self._drop_offers(task.id)
        claim = Claim(task=task, workers=workers, time=time)
        self.claims[task.id] = claim
        return claim

    def _drop_offers(self, task_id: str) -> None:
        self.offers = {agent: o for agent, o in self.offers.items() if o.task_id != task_id}


def _no_job(reference: str) -> str:
    named = job_id(reference)
    return (
        f"There is no {job_name(named)} on the board."
        if named
        else (f"There is no job {reference!r} on the board.")
    )
