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

A claim opens a workspace. When a claim ends by acceptance or abandonment its workspace is
closed at once; when it runs out, its workspace may be in use by a command still running, so it
is set aside and closed at the checkpoint. At the checkpoint every workspace is closed and the
changes of each held task are kept; the next `reopen` starts a fresh workspace and reapplies
them. Acceptance runs on the submitted diff in a fresh container, at most `acceptance_runs` a
day for each resident and task; a run whose checks could not be run at all (an `error`, the
machinery's failing) is not counted, and the count starts again at every checkpoint.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from world.backend import Backend, Task, Verdict, Workspace
from world.config import Work
from world.telling import counted, first_line

KEPT_CHANGES = "/tmp/kept-changes.patch"


@dataclass
class Claim:
    """`day` is the calendar day the claim was made."""

    task: int
    day: int
    diff: str = ""


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
    ) -> None:
        self.tasks = list(tasks)
        self.backend = backend
        self.work = work
        self.rotation = list(range(1, len(self.tasks) + 1))
        random.Random(f"{seed}:board").shuffle(self.rotation)
        self.posted: list[int] = []
        self.shared = shared
        self.money = money
        names = list(names)
        self.claims: dict[str, Claim] = {}
        self.done: dict[str, set[int]] = {name: set() for name in names}
        self.runs: dict[str, dict[int, int]] = {name: {} for name in names}
        self.workspaces: dict[str, Workspace] = {}
        self.orphans: list[Workspace] = []

    def task(self, number: int) -> Task:
        return self.tasks[number - 1]

    def post(self, day: int) -> None:
        """Post the board of calendar day `day`."""
        size = min(self.work.board_size, len(self.rotation))
        start = (day - 1) * size
        turn = [self.rotation[(start + i) % len(self.rotation)] for i in range(size)]
        self.posted = sorted(turn)

    def held_by_other(self, name: str, number: int) -> bool:
        return self.shared and any(
            claim.task == number for holder, claim in self.claims.items() if holder != name
        )

    def text(self, name: str, posting: str) -> str:
        """The posted tasks as `name` reads them, with the problem of the task it holds; with
        nothing posted, when the next board goes up, at the hour `posting`."""
        mine = self.claims.get(name)
        lines = []
        for number in self.posted:
            task = self.task(number)
            line = f"{number}. {task.repo}: {first_line(task.problem_statement)} Pays "
            line += f"{self.money(self.work.payment)}."
            if mine is not None and mine.task == number:
                line += " You hold it."
            elif number in self.done[name]:
                line += " You have been paid for it."
            elif self.held_by_other(name, number):
                line += " Held."
            lines.append(line)
        text = (
            "The board:\n" + "\n".join(lines)
            if lines
            else f"Nothing is posted on the board now; the next board goes up at {posting}."
        )
        if mine is not None:
            problem = self.task(mine.task).problem_statement
            text += f"\n\nThe problem of task {mine.task}, which you hold:\n\n{problem}"
        return text

    def claim_refusal(self, name: str, number: int) -> str | None:
        if number not in self.posted:
            return f"There is no task {number} on the board."
        if name in self.claims:
            return f"You already hold task {self.claims[name].task}; submit it or give it up first."
        if number in self.done[name]:
            return f"You have already been paid for task {number}."
        if self.held_by_other(name, number):
            return f"Task {number} is held by someone else."
        return None

    async def claim(self, name: str, number: int, day: int) -> Claim:
        """Hold task `number` for `name` and open its workspace."""
        claim = self.claims[name] = Claim(number, day)
        try:
            workspace = await self.backend.open(self.task(number), name)
        except BaseException:
            if self.claims.get(name) is claim:
                del self.claims[name]
            raise
        self._attach(name, claim, workspace)
        return claim

    async def reopen(self, name: str) -> None:
        """Open a fresh workspace for the task `name` holds and reapply its kept changes."""
        claim = self.claims[name]
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
        self._attach(name, claim, workspace)

    def _attach(self, name: str, claim: Claim, workspace: Workspace) -> None:
        if self.claims.get(name) is claim:
            self.workspaces[name] = workspace
        else:  # the claim ran out while the workspace was opening
            self.orphans.append(workspace)

    def runs_left(self, name: str, number: int) -> int:
        return self.work.acceptance_runs - self.runs[name].get(number, 0)

    def count_run(self, name: str, number: int) -> None:
        self.runs[name][number] = self.runs[name].get(number, 0) + 1

    def finish(self, name: str, claim: Claim) -> Workspace | None:
        """Mark the task of `name`'s claim, which it still holds, done for it, take it off a
        shared board, and release it; returns its workspace."""
        self.done[name].add(claim.task)
        if self.shared and claim.task in self.posted:
            self.posted.remove(claim.task)
        return self.drop(name)

    def drop(self, name: str) -> Workspace | None:
        """Release the task `name` holds; returns its workspace, for the caller to close."""
        del self.claims[name]
        return self.workspaces.pop(name, None)

    def expired(self, day: int) -> list[str]:
        """Who holds a claim that runs out at the midnight that ends calendar day `day`."""
        return [
            name
            for name, claim in self.claims.items()
            if claim.day + self.work.claim_expiry_days <= day
        ]

    async def close_all(self) -> list[tuple[str, Claim]]:
        """Close every workspace, keeping the changes of each held task; returns the claims
        whose workspaces were closed."""
        closed = []
        for name, workspace in list(self.workspaces.items()):
            claim = self.claims[name]
            claim.diff = await workspace.diff()
            await workspace.close()
            del self.workspaces[name]
            closed.append((name, claim))
        while self.orphans:
            await self.orphans.pop().close()
        return closed


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
