"""Work: the protocol between reality and task providers, and the task board.

A provider knows what a task is about and how to assess a solution. The board knows only
that a task was posted, claimed, delivered with a public result and a true quality, and
whether a defect of that delivery is still latent.
"""

import random
from typing import Protocol

from pydantic import Field, PositiveInt

from core.environment.rejection import Rejected
from core.interaction import day_of
from infrastructure.config import StrictModel


class Task(StrictModel):
    """A unit of paid work.

    `specification` is what workers see. `reference` is opaque to everyone but the provider,
    which assesses deliveries through it, also for tasks restored from a checkpoint. A
    claimant has `deadline_days` days, the day of claiming included, to deliver.
    """

    id: str
    title: str
    specification: str
    reward: PositiveInt
    deadline_days: PositiveInt
    reference: str


class Assessment(StrictModel):
    """A provider's verdict on a solution: whether its public result passes, the feedback
    shown to the worker, and its true quality in [0, 1], which only reality reveals."""

    passed: bool
    feedback: str
    quality: float = Field(ge=0, le=1)


class TaskProvider(Protocol):
    def sample(self, rng: random.Random, task_id: str) -> Task:
        """A new task with id `task_id`, drawn with `rng` and no other randomness."""
        ...

    async def assess(self, task: Task, solution: str) -> Assessment: ...


class Listing(StrictModel):
    """An open task and when it was put on the board."""

    task: Task
    time: int


class Claim(StrictModel):
    """An agent's exclusive claim on a task, with the feedback on its last failed delivery."""

    task: Task
    agent: str
    time: int
    feedback: str | None = None

    @property
    def due_day(self) -> int:
        """The last day on which the task can be delivered."""
        return day_of(self.time) + self.task.deadline_days - 1


class Delivery(StrictModel):
    """Accepted work: who delivered it and when, what it was paid, and its true quality."""

    task: Task
    worker: str
    time: int
    payment: int
    quality: float = Field(ge=0, le=1)


class Board:
    """Open listings by task id, active claims by agent (at most one each), and accepted
    deliveries whose defects are still latent. Task ids are `task-<n>`, counted from 1."""

    def __init__(
        self,
        next_number: int,
        listings: dict[str, Listing],
        claims: dict[str, Claim],
        latent: list[Delivery],
    ) -> None:
        self.next_number = next_number
        self.listings = listings
        self.claims = claims
        self.latent = latent

    def new_id(self) -> str:
        task_id = f"task-{self.next_number}"
        self.next_number += 1
        return task_id

    def post(self, task: Task, time: int) -> None:
        self.listings[task.id] = Listing(task=task, time=time)

    def claim(self, agent: str, task_id: str, time: int) -> Claim:
        """Give `agent` the open task `task_id`.

        Raises Rejected if the agent already holds a claim or the task is not open.
        """
        if held := self.claims.get(agent):
            raise Rejected(f"you already have a claimed task, {held.task.id}")
        if task_id not in self.listings:
            if any(claim.task.id == task_id for claim in self.claims.values()):
                raise Rejected(f"{task_id} is already claimed")
            raise Rejected(f"there is no open task {task_id!r}")
        claim = Claim(task=self.listings.pop(task_id).task, agent=agent, time=time)
        self.claims[agent] = claim
        return claim

    def claim_of(self, agent: str, task_id: str) -> Claim:
        """`agent`'s claim on `task_id`; raises Rejected if it holds none."""
        claim = self.claims.get(agent)
        if claim is None or claim.task.id != task_id:
            raise Rejected(f"you have no claim on {task_id!r}")
        return claim

    def record_failure(self, agent: str, feedback: str) -> None:
        """Keep `agent`'s claim open after a delivery that did not pass, with its feedback."""
        self.claims[agent] = self.claims[agent].model_copy(update={"feedback": feedback})

    def deliver(self, agent: str, time: int, payment: int, quality: float) -> Delivery:
        """Close `agent`'s claim as delivered; an imperfect delivery becomes a latent defect."""
        task = self.claims.pop(agent).task
        delivery = Delivery(task=task, worker=agent, time=time, payment=payment, quality=quality)
        if quality < 1:
            self.latent.append(delivery)
        return delivery

    def expire(self, time: int) -> list[Claim]:
        """End the claims due before the day of `time`, relisting their tasks; returns them."""
        expired = [claim for claim in self.claims.values() if claim.due_day < day_of(time)]
        for claim in expired:
            del self.claims[claim.agent]
            self.post(claim.task, time)
        return expired

    def retire(self, time: int, shelf_life_days: int) -> list[Task]:
        """Remove the tasks listed for `shelf_life_days` days or more by the day of `time`."""
        day = day_of(time)
        stale = [
            listing.task
            for listing in self.listings.values()
            if day - day_of(listing.time) >= shelf_life_days
        ]
        for task in stale:
            del self.listings[task.id]
        return stale

    def discover(self, rng: random.Random, probability: float) -> list[Delivery]:
        """Discover each latent defect with `probability`, one draw per defect; returns them."""
        hits = [rng.random() < probability for _ in self.latent]
        found = [delivery for delivery, hit in zip(self.latent, hits, strict=True) if hit]
        self.latent = [delivery for delivery, hit in zip(self.latent, hits, strict=True) if not hit]
        return found
