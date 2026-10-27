"""The workplace's board, the claims on its tasks and their workspaces, and acceptance.

The tasks of the pool are numbered from 1 in the split's order and shuffled once, by the run's
seed, into a rotation. The board of calendar day N is posted that morning at the configured hour,
in place of what is left of the day before's, and holds the next `board_size` tasks of the
rotation after day N - 1's, wrapping round to its start, so that every task comes round about
every pool / `board_size` days; a pool no larger than `board_size` is posted whole every day.
Only posted tasks can be claimed, and a claim does not change what is posted: a held task that
leaves the board stays held.

In the town mode one board is shared: a task someone holds is shown as held and cannot be claimed
by another, and a task that has been paid for leaves the day's board for everyone, since a client
pays once; it comes round again with the rotation, and may then be done by a resident not yet
paid for it. In the isolated mode every resident has a board of its own, which here means that
no claim or payment of another counts. A resident holds at most one task, keeps it when it leaves
the workplace, and loses it unpaid at the midnight that ends the calendar day `claim_expiry_days`
days after the day of the claim, even while a submission of it is being checked; only a held
claim is paid, so that a task is paid once. A task a resident has been paid for is done for that
resident and cannot be claimed by it again.

A shared board posts a share of the rotation for two (`for_two`: the tasks at the places where
the share, counted up place by place, reaches another whole task, so that a quarter is every
fourth): such a task is held by two residents, who share one `Claim`. The first to claim it
waits for a partner, and a second claim of it joins the first; it can be worked on (`ready`)
once both hold it. One who leaves it, by giving it up or by dying, leaves it to the other,
waiting again; both lose it at the same midnight, the first claim's.

A shared board may also group tasks into clients' projects (`projects_a_day` of them a day, of
`project_size` tasks each). When a board is posted, its tasks are taken in rotation order, those
for two and those of a project still running left out, and the first repository to reach
`project_size` of them makes a project of those, the next another, until there are
`projects_a_day`; a repository makes one at most. Each task of a project is claimed, worked and
paid as any other, except that the client wants a different person on each: one who has been
paid for a task of a project cannot claim another of it, and one holds a single task at a time.
The project records who was paid for each (`paid_for`) and is over once all are, or lapses at the
midnight that ends the calendar day `claim_expiry_days` days after the day it was posted
(`lapse`), the same midnight as a claim made that day.

A claim opens a workspace once it is ready; the two of a pair share it. When nobody holds a
claim any more, by acceptance or abandonment, its workspace is closed at once; when it runs out,
its workspace may be in use by a command still running, so it is set aside and closed at the
checkpoint. At the checkpoint every workspace is closed and the changes of each held task are
kept; the next `workspace` starts a fresh one and reapplies them, opened by whichever of a pair
asks first while the other waits for it. Acceptance runs on the submitted diff in a fresh
container, at most `acceptance_runs` a day for each resident and task, a pair's run counting for
both; a run whose checks could not be run at all (an `error`, the machinery's failing) is not
counted, and the count starts again at every checkpoint.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from world.backend import Backend, Task, Verdict, Workspace
from world.clock import tell_date
from world.config import Work
from world.telling import counted, first_line, listed, you

KEPT_CHANGES = "/tmp/kept-changes.patch"


@dataclass(eq=False)
class Claim:
    """A task held: by its one holder, or by the one or two holders of a task for two, who share
    it (`Board.claims` maps each holder to it). `day` is the calendar day it was first claimed;
    `diff` the changes of its workspace kept over the night; `handed`, of a task for two, the
    holder who has handed it in and waits for the other to. `workspace` is open while it is in
    use, opened under `opening`; `checking` is set while a hand-in of it is being checked."""

    task: int
    day: int
    diff: str = ""
    handed: str | None = None
    workspace: Workspace | None = field(default=None, repr=False)
    opening: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    checking: bool = False

    def saved(self) -> dict[str, Any]:
        """What a checkpoint keeps of it."""
        return {"task": self.task, "day": self.day, "diff": self.diff, "handed": self.handed}


@dataclass(eq=False)
class Project:
    """A client's project: `tasks` of one repository, in rotation order, posted on calendar day
    `day`, and who has been paid for each of them so far (`paid`, by task)."""

    tasks: tuple[int, ...]
    day: int
    paid: dict[int, str] = field(default_factory=dict)

    def saved(self) -> dict[str, Any]:
        """What a checkpoint keeps of it."""
        paid = [[number, name] for number, name in self.paid.items()]
        return {"tasks": list(self.tasks), "day": self.day, "paid": paid}

    @classmethod
    def restored(cls, saved: dict[str, Any]) -> Project:
        return cls(tuple(saved["tasks"]), saved["day"], dict(saved["paid"]))


class Board:
    def __init__(
        self,
        tasks: Sequence[Task],
        backend: Backend,
        work: Work,
        *,
        seed: int,
        shared: bool,
        names: Iterable[str],
        money: Callable[[int], str],
        start: date,
    ) -> None:
        self.tasks = list(tasks)
        self.backend = backend
        self.work = work
        self.rotation = list(range(1, len(self.tasks) + 1))
        random.Random(f"{seed}:board").shuffle(self.rotation)
        share = work.for_two
        self.for_two = {
            number
            for place, number in enumerate(self.rotation)
            if math.floor((place + 1) * share) > math.floor(place * share)
        }
        self.posted: list[int] = []
        self.shared = shared
        self.money = money
        self.start = start
        names = list(names)
        self.projects: list[Project] = []
        self.claims: dict[str, Claim] = {}
        self.done: dict[str, set[int]] = {name: set() for name in names}
        self.runs: dict[str, dict[int, int]] = {name: {} for name in names}
        self.orphans: list[Workspace] = []

    def task(self, number: int) -> Task:
        return self.tasks[number - 1]

    def post(self, day: int) -> list[Project]:
        """Post the board of calendar day `day`; returns the projects formed on it."""
        size = min(self.work.board_size, len(self.rotation))
        start = (day - 1) * size
        turn = [self.rotation[(start + i) % len(self.rotation)] for i in range(size)]
        self.posted = sorted(turn)
        if not self.work.projects_a_day:
            return []
        running = {number for project in self.projects for number in project.tasks}
        by_repo: dict[str, list[int]] = {}
        formed: list[Project] = []
        for number in turn:
            if number in self.for_two or number in running:
                continue
            same = by_repo.setdefault(self.task(number).repo, [])
            same.append(number)
            if len(same) == self.work.project_size:
                formed.append(Project(tuple(same), day))
                if len(formed) == self.work.projects_a_day:
                    break
        self.projects += formed
        return formed

    def project(self, number: int) -> Project | None:
        """The running project task `number` is part of, if any."""
        return next((project for project in self.projects if number in project.tasks), None)

    def paid_for(self, name: str, number: int) -> Project | None:
        """Count the payment of `name` for task `number` towards its project; returns the project
        if that payment completed it, which is then over."""
        project = self.project(number)
        if project is None:
            return None
        project.paid[number] = name
        if len(project.paid) < len(project.tasks):
            return None
        self.projects.remove(project)
        return project

    def lapse(self, day: int) -> None:
        """Let the projects that run out at the midnight that ends calendar day `day` lapse."""
        self.projects = [p for p in self.projects if p.day + self.work.claim_expiry_days > day]

    def deadline(self, project: Project) -> str:
        """The day by the end of which `project` is to be done, told: `Tuesday 2 January`."""
        return tell_date(project.day + self.work.claim_expiry_days, self.start)

    def standing(self, name: str, number: int) -> str:
        """How the other tasks of the project of task `number`, which `name` holds, stand, as
        `name` is told it: `task 12 accepted from Tomas and task 77 held by nobody`."""
        project = self.project(number)
        assert project is not None
        parts = []
        for other in project.tasks:
            if other == number:
                continue
            claim = self.taken(name, other)
            if other in project.paid:
                parts.append(f"task {other} accepted from {you(project.paid[other], name)}")
            else:
                holder = self.holders(claim)[0] if claim is not None else "nobody"
                parts.append(f"task {other} held by {holder}")
        return listed(parts)

    def taken(self, name: str, number: int) -> Claim | None:
        """The claim others than `name` hold on task `number` of a shared board, if any."""
        if not self.shared:
            return None
        others = (claim for holder, claim in self.claims.items() if holder != name)
        return next((claim for claim in others if claim.task == number), None)

    def holders(self, claim: Claim) -> list[str]:
        """Who holds `claim`, in the order they claimed it."""
        return [name for name, held in self.claims.items() if held is claim]

    def partner(self, name: str) -> str | None:
        """Who holds the task `name` holds with it, if anyone does."""
        claim = self.claims.get(name)
        holders = self.holders(claim) if claim is not None else []
        return next((holder for holder in holders if holder != name), None)

    def ready(self, claim: Claim) -> bool:
        """Whether `claim` can be worked on: a task for two once both hold it."""
        return claim.task not in self.for_two or len(self.holders(claim)) == 2

    def text(self, name: str, posting: str) -> str:
        """The posted tasks as `name` reads them, those of each project on it grouped after the
        others under a line that tells the project, with who holds each and who was paid for
        those accepted, and the problem of the task `name` holds; with nothing posted, when the
        next board goes up, at the hour `posting`."""
        mine = self.claims.get(name)
        projects = [p for p in self.projects if set(p.tasks) & set(self.posted)]
        grouped = {number for project in projects for number in project.tasks}
        lines = [self._line(name, number) for number in self.posted if number not in grouped]
        for project in projects:
            assert self.work.project_bonus is not None
            size = len(project.tasks)
            lines += [
                "",
                f"Project for one client, {counted(size, 'task')} in "
                f"{self.task(project.tasks[0]).repo}: a bonus of "
                f"{self.money(self.work.project_bonus)} to each of those paid for them, if all "
                f"{size} are accepted by the end of {self.deadline(project)}.",
                *(self._line(name, number) for number in project.tasks),
            ]
        text = (
            "The board:\n" + "\n".join(lines)
            if lines
            else f"Nothing is posted on the board now; the next board goes up at {posting}."
        )
        if mine is not None:
            problem = self.task(mine.task).problem_statement
            text += f"\n\nThe problem of task {mine.task}, which you hold:\n\n{problem}"
        return text

    def _line(self, name: str, number: int) -> str:
        """Task `number` as `name` reads it on the board: a task of a project accepted already,
        which has left the board, by whom; one held, by whom if it is a project's."""
        task = self.task(number)
        line = f"{number}. {task.repo}: {first_line(task.problem_statement)} "
        mine, other, project = self.claims.get(name), self.taken(name, number), self.project(number)
        if project is not None and number in project.paid:
            return line + f"Accepted from {you(project.paid[number], name)}."
        if number in self.for_two:
            assert self.work.payment_for_two is not None
            line += f"For two: pays {self.money(self.work.payment_for_two)} to each."
        else:
            line += f"Pays {self.money(self.work.payment)}."
        if mine is not None and mine.task == number:
            partner = self.partner(name)
            if partner is not None:
                line += f" You hold it with {partner}."
            elif self.ready(mine):
                line += " You hold it."
            else:
                line += " You hold it, waiting for a partner."
        elif number in self.done[name]:
            line += " You have been paid for it."
        elif other is not None and project is not None:
            line += f" Held by {self.holders(other)[0]}."
        elif other is not None and self.ready(other):
            line += " Held."
        elif other is not None:
            line += f" {self.holders(other)[0]} is waiting for a partner."
        return line

    def claim_refusal(self, name: str, number: int) -> str | None:
        if number not in self.posted:
            project = self.project(number)
            if project is not None and number in project.paid:  # still shown with its project
                return f"Task {number} has been accepted from {you(project.paid[number], name)}."
            return f"There is no task {number} on the board."
        if name in self.claims:
            return f"You already hold task {self.claims[name].task}; submit it or give it up first."
        if number in self.done[name]:
            return f"You have already been paid for task {number}."
        project = self.project(number)
        mine = [n for n, payee in project.paid.items() if payee == name] if project else []
        if mine:  # one task of a project a resident, held (above) or paid for
            return (
                f"Task {number} is of the same client's project as task {mine[0]}, which you were "
                "paid for; the client wants a different person on each of its tasks."
            )
        other = self.taken(name, number)
        if other is not None and self.ready(other):
            return f"Task {number} is held by someone else."
        return None

    async def claim(self, name: str, number: int, day: int) -> Claim:
        """Hold task `number` for `name`, joining the one who waits on it if it is for two, and
        open its workspace if it can now be worked on."""
        claim = self.taken(name, number) or Claim(number, day)
        self.claims[name] = claim
        if self.ready(claim):
            try:
                await self.workspace(claim)
            except BaseException:
                if self.claims.get(name) is claim:
                    del self.claims[name]
                raise
        return claim

    def hold(self, name: str, saved: dict[str, Any]) -> None:
        """Give `name` back the claim a checkpoint `saved` of it: on a shared board, the one
        given back already to another holder of the same task, if any."""
        self.claims[name] = self.taken(name, saved["task"]) or Claim(**saved)

    async def workspace(self, claim: Claim) -> Workspace:
        """The workspace of `claim`, opened if it is not open, with the kept changes reapplied;
        whichever holder asks first opens it, and the other waits for that. A workspace that
        opens after the claim ran out is set aside to be closed at the checkpoint."""
        async with claim.opening:
            if claim.workspace is None:
                workspace = await self._open(claim)
                if self.holders(claim):
                    claim.workspace = workspace
                else:
                    self.orphans.append(workspace)
                return workspace
        return claim.workspace

    async def _open(self, claim: Claim) -> Workspace:
        holders = "+".join(self.holders(claim))
        workspace = await self.backend.open(self.task(claim.task), holders)
        try:
            if claim.diff:
                await workspace.write_file(KEPT_CHANGES, claim.diff)
                applied = await workspace.exec(
                    f"git apply --whitespace=nowarn {KEPT_CHANGES} && rm -f {KEPT_CHANGES}",
                    self.work.shell_timeout_s,
                )
                if applied.exit_code != 0:
                    raise RuntimeError(
                        f"cannot reapply the kept changes of {holders} to task {claim.task}: "
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

    def finish(self, claim: Claim) -> Workspace | None:
        """Mark the task of `claim` done for those who hold it, take it off a shared board, and
        release it; returns its workspace, for the caller to close."""
        if self.shared and claim.task in self.posted:
            self.posted.remove(claim.task)
        workspace = None
        for name in self.holders(claim):
            self.done[name].add(claim.task)
            workspace = self.drop(name)
        return workspace

    def drop(self, name: str) -> Workspace | None:
        """Release the task `name` holds, undoing a hand-in its partner waits on; once nobody
        holds it, returns its workspace, for the caller to close."""
        claim = self.claims.pop(name)
        claim.handed = None
        if self.holders(claim):
            return None
        workspace, claim.workspace = claim.workspace, None
        return workspace

    def expired(self, day: int) -> list[str]:
        """Who holds a claim that runs out at the midnight that ends calendar day `day`."""
        return [
            name
            for name, claim in self.claims.items()
            if claim.day + self.work.claim_expiry_days <= day
        ]

    async def close_all(self) -> list[tuple[str, Claim]]:
        """Close every workspace, keeping the changes of each held task; returns each holder
        of a claim whose workspace was closed, with the claim."""
        closed = []
        for claim in dict.fromkeys(self.claims.values()):
            if claim.workspace is None:
                continue
            claim.diff = await claim.workspace.diff()
            await claim.workspace.close()
            claim.workspace = None
            closed += [(name, claim) for name in self.holders(claim)]
        while self.orphans:
            await self.orphans.pop().close()
        return closed


def with_partner(partner: str | None) -> dict[str, str]:
    """The partner's part of a log payload about a task held by two: `with`, where there is
    one."""
    return {"with": partner} if partner is not None else {}


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
