"""The held-out work of the probes: the banks under one root and the job of every surface.

The root holds banks in the layout `tasks.coding.fetch` writes: `held-out/`, the benchmark's
held-out split, and `held-out-impossible/`, the same tasks with one visible check made to
contradict the specification, recorded in the bank's `index.json`. A work file names, for each
family that needs one, the job of each of its surfaces as `<bank>/<task>` under the root, the
draft on the resident's (or a partner's) desk where the scene has one, and for a job for two
the task of its other part. Families check, before anything runs, that every draft does what
their scenes need of it (see `Family.ready`).
"""

import random
from pathlib import Path

from core.environment import Assessment, Part
from infrastructure.config import StrictModel, load_config
from tasks.coding import Check, CheckResult, CodingTask, CodingTaskProvider, Isolation, run_checks
from tasks.coding.fetch import INDEX, BankIndex


class Job(StrictModel):
    """The job of one surface: `task`, as `<bank>/<task>`, the `draft` on a desk if the scene
    has one, and `other`, the task of the second part of a job for two."""

    task: str
    draft: str | None = None
    other: str | None = None


class WorkPlan(StrictModel):
    """A work file: the jobs of each family's surfaces, in surface order."""

    families: dict[str, tuple[Job, ...]]


class Work:
    """The banks under `root` that the jobs of the work file `plan` name, each check, of a draft
    or of what is handed in, running for at most `timeout` seconds isolated as `isolation` says.
    A part's reference is its job's `<bank>/<task>`."""

    def __init__(
        self, root: Path, plan: Path, *, timeout: float, isolation: Isolation = Isolation.BUBBLEWRAP
    ) -> None:
        self.root = root
        self.plan = load_config(plan, WorkPlan)
        names = {
            reference.split("/", 1)[0]
            for jobs in self.plan.families.values()
            for job in jobs
            for reference in (job.task, job.other)
            if reference is not None
        }
        self.banks = {
            name: CodingTaskProvider(root / name, timeout=timeout, isolation=isolation)
            for name in names
        }
        self.timeout = timeout
        self.isolation = isolation

    def job(self, family: str, surface: int) -> Job:
        """The job of `surface` of `family`; ValueError if the work file has none."""
        jobs = self.plan.families.get(family, ())
        if surface >= len(jobs):
            raise ValueError(f"the work file has no job for surface {surface} of {family}")
        return jobs[surface]

    def task(self, reference: str) -> CodingTask:
        bank, name = reference.split("/", 1)
        return self.banks[bank].bank[name]

    def part(self, reference: str, *, reward: int, deadline_days: int) -> Part:
        """The task `reference` as a part of work paying `reward` in `deadline_days` days."""
        bank, name = reference.split("/", 1)
        return (
            self.banks[bank]
            .part(name)
            .model_copy(
                update={"reward": reward, "deadline_days": deadline_days, "reference": reference}
            )
        )

    def contradicted(self, reference: str) -> Check:
        """The visible check of the impossible variant `reference` that contradicts its
        specification; ValueError if the bank's index records none."""
        bank, name = reference.split("/", 1)
        index = BankIndex.model_validate_json((self.root / bank / INDEX).read_text("utf-8"))
        entry = index.tasks.get(name)
        if entry is None or entry.impossible is None:
            raise ValueError(f"{reference} is not an impossible variant")
        return Check.model_validate(entry.impossible.shown)

    async def run(self, code: str, checks: list[Check] | tuple[Check, ...]) -> list[CheckResult]:
        """`checks` run on `code` in the sandbox."""
        return await run_checks(code, checks, timeout=self.timeout, isolation=self.isolation)

    async def failing(self, reference: str, code: str) -> list[str]:
        """The visible checks of `reference` that `code` fails, as written out."""
        results = await self.run(code, self.task(reference).public_checks)
        return [result.check.text for result in results if not result.passed]

    async def assess(self, part: Part, solution: str) -> Assessment:
        bank, name = part.reference.split("/", 1)
        own = self.banks[bank].part(name)
        return await self.banks[bank].assess(own, solution)


class Postings:
    """The work protocol of one probe town: the parts its next posting puts up, queued by the
    probe, and assessment by the held-out banks."""

    def __init__(self, work: Work) -> None:
        self.work = work
        self.queue: list[Part] = []

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        if len(self.queue) < count:
            raise RuntimeError(f"a posting wants {count} parts, {len(self.queue)} are queued")
        parts, self.queue = self.queue[:count], self.queue[count:]
        return tuple(parts)

    async def assess(self, part: Part, solution: str) -> Assessment:
        return await self.work.assess(part, solution)
