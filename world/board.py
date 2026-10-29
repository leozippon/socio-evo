"""The Office's board: the clients' tasks as they arrive, who holds which, their workspaces,
acceptance, and the tasks the clients withdraw.

The tasks of the pool are numbered from 1 in the split's order and shuffled once, by the run's
seed, into a rotation. The arrivals of each calendar day are drawn at the midnight before it
(`draw`), from the run's seed and the day alone: a Poisson count with mean `tasks_a_day`, each at
a minute drawn uniformly from `arrive_from` up to `arrive_until`. Each arrival takes the next task
of the rotation, so that a task comes once in a run; a pool used up is an error. A task that has
come is open (`open`, with the calendar day it came) until it is accepted, which pays the client's
payment once, or withdrawn by its client, held or not, at the midnight that ends the calendar day
`expiry_days` days after the day it came; either way it is gone for good.

A resident holds at most one task (`claims`): taken with `claim`, or given to it by the team
leader (`give`), which may move a task from one holder to another. It keeps the task wherever it
goes until it is accepted, given up, moved or withdrawn. A claim opens a workspace when its holder
first works on it. When its holder gives the claim up or is paid, the workspace is closed at once;
when the task is moved or withdrawn, the workspace may be in use by a command still running, so
it is set aside and closed at the checkpoint, its changes gone with it. At the checkpoint every
workspace is closed and the changes of each held task are kept; the next `workspace` starts a
fresh one and reapplies them. Acceptance runs on the submitted diff in a fresh container, at most
`acceptance_runs` a day for each resident and task; a run whose checks could not be run at all
(an `error`, the machinery's failing) is not counted, and the count starts again at every
checkpoint.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from world.backend import Backend, Task, Verdict, Workspace
from world.clock import DAY, parse_hour
from world.config import TownConfig
from world.telling import counted, first_line

KEPT_CHANGES = "/tmp/kept-changes.patch"


@dataclass(eq=False)
class Claim:
    """A task held (`Board.claims` maps its holder to it). `diff` is the changes of its workspace
    kept over the night; `workspace` is open while it is in use."""

    task: int
    diff: str = ""
    workspace: Workspace | None = field(default=None, repr=False)

    def saved(self) -> dict[str, Any]:
        """What a checkpoint keeps of it."""
        return {"task": self.task, "diff": self.diff}


def poisson(rng: random.Random, mean: float) -> int:
    """A count drawn from the Poisson distribution of `mean` (Knuth's method)."""
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


class Board:
    def __init__(
        self,
        tasks: Sequence[Task],
        backend: Backend,
        town: TownConfig,
        *,
        names: Iterable[str],
    ) -> None:
        self.tasks = list(tasks)
        self.backend = backend
        self.town = town
        self.work = town.work
        self.seed = town.seed
        self.rotation = list(range(1, len(self.tasks) + 1))
        random.Random(f"{self.seed}:board").shuffle(self.rotation)
        self.arrived = 0
        """How many tasks of the rotation have come."""
        self.schedule: list[int] = []
        """The times of the arrivals still to come today."""
        self.open: dict[int, int] = {}
        """The tasks open on the board, each with the calendar day it came."""
        self.claims: dict[str, Claim] = {}
        self.runs: dict[str, dict[int, int]] = {name: {} for name in names}
        self.orphans: list[Workspace] = []

    def task(self, number: int) -> Task:
        return self.tasks[number - 1]

    def draw(self, day: int) -> list[int]:
        """The times at which tasks arrive on calendar day `day`, from the run's seed."""
        rng = random.Random(f"{self.seed}:arrivals:{day}")
        count = poisson(rng, self.work.tasks_a_day)
        first, last = (
            parse_hour(hour) // 60 for hour in (self.work.arrive_from, self.work.arrive_until)
        )
        return sorted((day - 1) * DAY + rng.randrange(first, last) * 60 for _ in range(count))

    def arrive(self, day: int) -> int:
        """The next task of the rotation comes, on calendar day `day`; returns its number."""
        if self.arrived >= len(self.rotation):
            raise RuntimeError(f"the pool of {len(self.rotation)} tasks is used up")
        number = self.rotation[self.arrived]
        self.arrived += 1
        self.open[number] = day
        return number

    def withdrawn_on(self, number: int) -> int:
        """The calendar day at whose end the client withdraws task `number`."""
        return self.open[number] + self.work.expiry_days

    def holder(self, number: int) -> str | None:
        """Who holds task `number`, if anyone."""
        return next((name for name, claim in self.claims.items() if claim.task == number), None)

    def text(self, name: str, date: Callable[[int], str]) -> str:
        """The open tasks as `name` reads them, with who holds each and when the client withdraws
        it (`date` tells a calendar day), and the problem of the task `name` holds."""
        mine = self.claims.get(name)
        lines = [self._line(name, number, date) for number in sorted(self.open)]
        text = "The board:\n" + "\n".join(lines) if lines else "No task is open on the board now."
        if mine is not None:
            problem = self.task(mine.task).problem_statement
            text += f"\n\nThe problem of task {mine.task}, which you hold:\n\n{problem}"
        return text

    def _line(self, name: str, number: int, date: Callable[[int], str]) -> str:
        """Task `number` as `name` reads it on the board."""
        task = self.task(number)
        pays = self.town.money(self.work.payment)
        problem = first_line(task.problem_statement)
        until = date(self.withdrawn_on(number))
        line = (
            f"{number}. {task.repo}: {problem} The client pays {pays} and withdraws it at the end "
            f"of {until}."
        )
        holder = self.holder(number)
        if holder == name:
            line += " You hold it."
        elif holder is not None:
            line += f" {holder} holds it."
        return line

    def claim_refusal(self, name: str, number: int) -> str | None:
        if number not in self.open:
            return f"There is no task {number} on the board."
        if name in self.claims:
            return f"You already hold task {self.claims[name].task}; submit it or give it up first."
        holder = self.holder(number)
        if holder is not None:
            return f"Task {number} is held by {holder}."
        return None

    async def claim(self, name: str, number: int) -> Claim:
        """Hold task `number` for `name` and open its workspace."""
        claim = Claim(number)
        self.claims[name] = claim
        try:
            await self.workspace(name, claim)
        except BaseException:
            if self.claims.get(name) is claim:
                del self.claims[name]
            raise
        return claim

    def give(self, name: str, number: int) -> str | None:
        """`name` holds the open task `number`, given to it, its workspace opened when it first
        works on it; the one who held it, if anyone, holds it no more, its workspace set aside;
        returns that one."""
        before = self.holder(number)
        if before is not None:
            self._set_aside(before)
        self.claims[name] = Claim(number)
        return before

    def hold(self, name: str, saved: dict[str, Any]) -> None:
        """Give `name` back the claim a checkpoint `saved` of it."""
        self.claims[name] = Claim(**saved)

    async def workspace(self, name: str, claim: Claim) -> Workspace:
        """The workspace of `claim`, which `name` holds, opened if it is not open, with the kept
        changes reapplied. A workspace that opens after the claim ended is set aside to be closed
        at the checkpoint."""
        if claim.workspace is None:
            workspace = await self._open(name, claim)
            if self.claims.get(name) is claim:
                claim.workspace = workspace
            else:
                self.orphans.append(workspace)
            return workspace
        return claim.workspace

    async def _open(self, name: str, claim: Claim) -> Workspace:
        workspace = await self.backend.open(self.task(claim.task), name)
        try:
            if claim.diff:
                await workspace.write_file(KEPT_CHANGES, claim.diff)
                applied = await workspace.exec(
                    f"git apply --whitespace=nowarn {KEPT_CHANGES} && rm -f {KEPT_CHANGES}",
                    self.work.shell_timeout_s,
                )
                if applied.exit_code != 0:
                    raise RuntimeError(
                        f"cannot reapply the kept changes of {name} to task {claim.task}: "
                        f"{applied.stderr.strip() or applied.stdout.strip()}"
                    )
        except BaseException:
            await workspace.close()
            raise
        return workspace

    def runs_left(self, name: str, number: int) -> int:
        return self.work.acceptance_runs - self.runs[name].get(number, 0)

    def count_run(self, name: str, number: int) -> None:
        self.runs[name][number] = self.runs[name].get(number, 0) + 1

    def finish(self, name: str) -> Workspace | None:
        """The task `name` holds was accepted: it leaves the board and `name`; returns its
        workspace, for the caller to close."""
        del self.open[self.claims[name].task]
        return self.drop(name)

    def drop(self, name: str) -> Workspace | None:
        """Release the task `name` holds; returns its workspace, for the caller to close."""
        claim = self.claims.pop(name)
        workspace, claim.workspace = claim.workspace, None
        return workspace

    def _set_aside(self, name: str) -> None:
        """Release the task `name` holds, its workspace to be closed at the checkpoint."""
        workspace = self.drop(name)
        if workspace is not None:
            self.orphans.append(workspace)

    def withdraw(self, day: int) -> list[tuple[int, str | None]]:
        """The clients withdraw the tasks whose time runs out at the midnight that ends calendar
        day `day`; returns each with who held it."""
        ending = [number for number in sorted(self.open) if self.withdrawn_on(number) <= day]
        withdrawn = []
        for number in ending:
            holder = self.holder(number)
            if holder is not None:
                self._set_aside(holder)
            del self.open[number]
            withdrawn.append((number, holder))
        return withdrawn

    async def close_all(self) -> list[tuple[str, Claim]]:
        """Close every workspace, keeping the changes of each held task; returns each holder
        of a claim whose workspace was closed, with the claim."""
        closed = []
        for name, claim in self.claims.items():
            if claim.workspace is None:
                continue
            claim.diff = await claim.workspace.diff()
            await claim.workspace.close()
            claim.workspace = None
            closed.append((name, claim))
        while self.orphans:
            await self.orphans.pop().close()
        return closed

    def saved(self) -> dict[str, Any]:
        """What a checkpoint keeps of the board, beside the claims: how many tasks have come,
        the arrivals still to come and the open tasks, each `[task, the day it came]`."""
        return {
            "arrived": self.arrived,
            "schedule": list(self.schedule),
            "open": [[number, day] for number, day in sorted(self.open.items())],
        }

    def restore(self, saved: dict[str, Any]) -> None:
        self.arrived = saved["arrived"]
        self.schedule = list(saved["schedule"])
        self.open = {number: day for number, day in saved["open"]}


def failure(verdict: Verdict) -> str:
    """Why a verdict did not accept, as the resident reads it: the kind of failure and how many
    checks failed, never which."""
    if verdict.status == "patch_apply_failed":
        return "your changes could not be applied to a clean copy of the repository"
    if verdict.status == "timeout":
        return "checking your changes took too long and was stopped"
    if verdict.status == "error":
        return "the checks could not be run on your changes"
    passed, total = verdict.fail_to_pass
    kept, before = verdict.pass_to_pass
    parts = []
    if passed < total:
        parts.append(
            f"{total - passed} of the {counted(total, 'check')} your change should make "
            "pass did not pass"
        )
    if kept < before:
        parts.append(f"{before - kept} of the {counted(before, 'check')} that passed before failed")
    return " and ".join(parts) or "the checks did not all pass"
