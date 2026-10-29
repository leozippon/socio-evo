"""The Office: its board of the clients' tasks, their arrivals and withdrawals, the claims on
them, the work done in their workspaces, and the Office's day as the team leader's statement
tells it.

The tasks of the pool are numbered from 1 in the split's order and shuffled once, by the run's
seed, into a rotation. The arrivals of each calendar day are drawn at the midnight before it
(`Board.draw`), from the run's seed and the day alone: a Poisson count with mean `tasks_a_day`,
each at a minute drawn uniformly from `arrive_from` up to `arrive_until`. Each arrival takes the
next task of the rotation, so that a task comes once in a run; a pool used up is an error. A task
that has come is open (`open`, with the calendar day it came) until it is accepted, which pays the
client's payment once, or withdrawn by its client, held or not, at the midnight that ends the
calendar day `expiry_days` days after the day it came; either way it is gone for good. An arrival
is told to those awake at the Office (`arrival`), a withdrawal to whoever held the task
(`withdrawals`).

A resident holds at most one task (`claims`): taken with `claim_task`, or given to it by the team
leader (`assign`), which may move a task from one holder to another. It keeps the task wherever
it goes until it is accepted, given up, moved or withdrawn. A claim opens a workspace when its
holder first works on it. When its holder gives the claim up or is paid, the workspace is closed
at once; when the task is moved or withdrawn, the workspace may be in use by a command still
running, so it is set aside and closed at the checkpoint, its changes gone with it. At the
checkpoint every workspace is closed and the changes of each held task are kept; the next
`workspace` starts a fresh one and reapplies them. Acceptance runs on the submitted diff in a
fresh container, at most `acceptance_runs` a day for each resident and task; a run whose checks
could not be run at all (an `error`, the machinery's failing) is not counted, and the count starts
again at every checkpoint (`Board.new_day`).

The Office's tools (`HANDLERS`) read the board and a task's problem there, claim, assign, act in
the workspace of the task one holds (`world.workspace` does and tells what they do there; the
handlers add the claim they need and the log entry), hand the task in and give it up. Claiming,
assigning and acting in a workspace sit the resident down to work, as `start_work` does; the work
on a task is done at the Office only, where the machines are. A command stopped by its limit of
real time, which the town's clock outruns, is told as having run too long, with the hour.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.port import ToolResult
from world.backend import Backend, Task, Workspace
from world.clock import DAY, calendar_day, clock_time, parse_hour, tell_date
from world.config import TownConfig
from world.telling import cap, counted, first_line, listed, you
from world.tools import Handler, hour_told, sit_down, working_at
from world.workspace import edit_repo, failure, read_repo, told_command, write_repo

if TYPE_CHECKING:
    from world.world import Resident, World

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

    def new_day(self) -> None:
        """The checkpoint: the hand-ins counted start again."""
        self.runs = {name: {} for name in self.runs}

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


def arrival(world: World, t: int) -> None:
    """A client's task, due at `t`, comes in on the board: told to those awake at the
    Office."""
    board = world.board
    board.schedule.remove(t)
    number = board.arrive(calendar_day(t))
    task = board.task(number)
    office = world.config.workplace("office")
    here = [r for r in world.residents.values() if r.place == office.id and r.awake]
    hour = clock_time(t)
    world.record(
        "task_arrived",
        lambda w: f"It is {hour}: task {number} ({task.repo}) came in on the board.",
        place=office.id,
        audience=here,
        payload={"task": number, "instance_id": task.instance_id, "repo": task.repo},
    )


def withdrawals(world: World, day: int) -> None:
    """The clients withdraw the tasks not accepted in time, told to whoever held each."""
    office = world.config.workplace("office").id
    for number, holder in world.board.withdraw(day):
        held = [world.residents[holder]] if holder is not None else []
        world.record(
            "task_withdrawn",
            lambda w, number=number, holder=holder: (
                f"At midnight the client withdrew task {number}, which you held; its "
                "workspace is gone."
                if w is not None and w == holder
                else f"At midnight the client withdrew task {number}."
            ),
            place=office,
            audience=held,
            payload={"task": number, "holder": holder},
        )


def day_told(world: World, r: Resident, day: int) -> str:
    """The Office's day, as the team leader `r`'s statement tells it at the midnight that
    ends calendar day `day`, before the clients withdraw what is out of time: the tasks
    accepted that day and by whom (the daybook's), those the clients withdraw at this
    midnight and who held them, and the tasks left open on the board, with those that came
    in that day and who holds each."""
    board = world.board
    accepted = [
        f"task {task} by {you(name, r.name)}" for name, task in world.daybook.today["accepted"]
    ]
    withdrawn, left = [], []
    for number in sorted(board.open):
        holder = board.holder(number)
        if board.withdrawn_on(number) <= day:
            held = f", which {you(holder, r.name)} held" if holder is not None else ""
            withdrawn.append(f"task {number}{held}")
            continue
        came = ", which came in today" if board.open[number] == day else ""
        held = f"held by {you(holder, r.name)}" if holder is not None else "held by nobody"
        left.append(f"task {number} ({board.task(number).repo}){came}, {held}")
    told = [
        f"{cap(world.config.workplace('office').name)} today. Accepted: "
        f"{listed(accepted) or 'none'}."
    ]
    if withdrawn:
        told.append(f"Withdrawn by the clients at midnight: {'; '.join(withdrawn)}.")
    told.append(f"Open on the board: {'; '.join(left) or 'nothing'}.")
    return " ".join(told)


def _away(world: World, r: Resident) -> ToolResult | None:
    """The refusal of `r`'s reading or claiming from the board away from the Office, where it
    hangs for whoever is there to read; None at the Office."""
    office = world.config.workplace("office")
    return ToolResult(f"You are not at {office.name}.") if r.place != office.id else None


async def _view_board(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    if away := _away(world, r):
        return away
    start = world.config.start_date
    return ToolResult(world.board.text(r.name, lambda day: tell_date(day, start)))


async def _read_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    number, board = args["task"], world.board
    if away := _away(world, r):
        return away
    if number not in board.open:
        return ToolResult(f"There is no task {number} on the board.")
    task = board.task(number)
    return ToolResult(f"The problem of task {number}, in {task.repo}:\n\n{task.problem_statement}")


async def _claim_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    number, board = args["task"], world.board
    if away := _away(world, r):
        return away
    refusal = board.claim_refusal(r.name, number)
    if refusal:
        return ToolResult(refusal)
    sat = sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    await board.claim(r.name, number)
    task = board.task(number)
    world.record(
        "claim",
        lambda w: f"{cap(you(r.name, w))} claimed task {number} ({task.repo}).",
        actor=r,
        payload={"task": number, "instance_id": task.instance_id},
    )
    sat = "sat down to work and " if sat else ""
    return ToolResult(
        f"You {sat}claimed task {number}, in {task.repo}; your workspace is ready. "
        f"{hour_told(world)} The problem:\n\n{task.problem_statement}"
    )


async def _assign(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    number, name, board = args["task"], args["to"], world.board
    sat = working_at(world, r, "office")
    if isinstance(sat, ToolResult):
        return sat
    other = world.residents.get(name)
    if other is None or other.occupation.id != "programmer":
        return ToolResult(f"{sat}{name} is not one of the programmers.")
    if number not in board.open:
        return ToolResult(f"{sat}There is no task {number} on the board.")
    before = board.holder(number)
    if before == name:
        return ToolResult(f"{sat}{name} holds task {number} already.")
    if name in board.claims:
        return ToolResult(f"{sat}{name} holds task {board.claims[name].task} already.")
    board.give(name, number)
    task = board.task(number)
    moved = [world.residents[before]] if before is not None else []

    def told(w: str | None) -> str:
        held = "" if before is None else f", which {you(before, w)} held,"
        given = f"{cap(you(r.name, w))} gave task {number} ({task.repo}){held} to {you(name, w)}"
        gone = before is not None and w == before
        return f"{given}; your changes to it are gone." if gone else f"{given}."

    world.record(
        "assign",
        told,
        actor=r,
        audience=[other, *moved],
        payload={"task": number, "to": name, "from": before},
    )
    return ToolResult(f"{sat}{told(r.name)}")


NO_TASK = "You hold no task; claim one from the board first."


async def _workspace(world: World, r: Resident) -> tuple[Claim, Workspace, str] | ToolResult:
    """The task `r` holds and its workspace, reopened if the night closed it, with `r` sat down
    to work if it was not, and what it is told of sitting down, or nothing. The work is done
    at the office, where the machines are."""
    claim = world.board.claims.get(r.name)
    if claim is None:
        return ToolResult(NO_TASK)
    office = world.config.workplace("office")
    if r.place != office.id:
        return ToolResult(f"You can work on task {claim.task} only at {office.name}.")
    sat = sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    workspace = await world.board.workspace(r.name, claim)
    if world.board.claims.get(r.name) is not claim:  # the claim ran out while it opened
        return ToolResult(f"{sat}{NO_TASK}")
    return claim, workspace, sat


async def _shell(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number = claim.task
    result = await workspace.exec(args["command"], world.config.work.shell_timeout_s)
    command = args["command"]
    world.record(
        "command",
        lambda w: (
            f"{cap(you(r.name, w))} ran a command for task {number}: "
            f"{command[:200]} (exit code {result.exit_code})."
        ),
        actor=r,
        payload={
            "task": number,
            "command": command,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "output_tail": (result.stdout + result.stderr)[-1000:],
        },
    )
    # The limit is of real time, which the town's clock outruns: told in the town's hours.
    return ToolResult(
        sat + told_command(result, f"The command ran too long and was stopped. {hour_told(world)}")
    )


async def _read_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number, path = claim.task, args["path"]
    told, ok = await read_repo(workspace, args)
    world.record(
        "file_read",
        lambda w: f"{cap(you(r.name, w))} read {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "ok": ok},
    )
    return ToolResult(sat + told)


async def _write_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number, path = claim.task, args["path"]
    told, ok = await write_repo(workspace, args)
    world.record(
        "file_write",
        lambda w: f"{cap(you(r.name, w))} wrote {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "characters": len(args["content"]), "ok": ok},
    )
    return ToolResult(sat + told)


async def _edit_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number, path = claim.task, args["path"]
    told, ok = await edit_repo(workspace, args)
    world.record(
        "file_write",
        lambda w: f"{cap(you(r.name, w))} changed {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "edit": True, "ok": ok},
    )
    return ToolResult(sat + told)


async def _submit(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    result = await _hand_in(world, r, claim, workspace)
    return ToolResult(sat + result.text, result.ends_turn)


async def _hand_in(world: World, r: Resident, claim: Claim, workspace: Workspace) -> ToolResult:
    """`r` hands in the task it holds, `claim`, from `workspace`: what `submit` tells."""
    board = world.board
    number = claim.task
    if board.runs_left(r.name, number) <= 0:
        return ToolResult(
            f"You have handed in task {number} {counted(world.config.work.acceptance_runs, 'time')}"
            " today, as often as a day allows; you can hand it in again tomorrow."
        )
    patch = await workspace.diff()
    if not patch.strip():
        return ToolResult("Your workspace has no changes to hand in.")
    task = board.task(number)
    world.record(
        "submission",
        lambda w: f"{cap(you(r.name, w))} handed in task {number}.",
        actor=r,
        payload={"task": number, "patch": patch},
    )
    verdict = await board.backend.accept(task, patch, world.config.work.acceptance_timeout_s)
    if verdict.status != "error":  # checks that could not be run use up no hand-in
        board.count_run(r.name, number)
    left = board.runs_left(r.name, number)
    holds = board.claims.get(r.name) is claim  # withdrawn or moved while the checks ran?
    world.record(
        "verdict",
        lambda w: (
            f"Task {number}, handed in by {you(r.name, w)}, was "
            + ("accepted." if verdict.resolved else f"not accepted: {failure(verdict)}.")
        ),
        actor=r,
        payload={
            "task": number,
            "status": verdict.status,
            "resolved": verdict.resolved,
            "fail_to_pass": list(verdict.fail_to_pass),
            "pass_to_pass": list(verdict.pass_to_pass),
            "held": holds,
        },
    )
    if not holds:  # withdrawn or given to another while the checks ran: nobody is paid for it
        told = "Accepted" if verdict.resolved else f"Not accepted: {failure(verdict)}"
        unpaid = ", so you are not paid for it" if verdict.resolved else ""
        return ToolResult(
            f"{told}. Task {number} was no longer yours by the time the checks finished"
            f"{unpaid}. {hour_told(world)}"
        )
    if not verdict.resolved:
        again = (
            f"You can hand in task {number} {counted(left, 'more time')} today."
            if left > 0
            else f"You cannot hand in task {number} again today."
        )
        if verdict.status == "error":
            told = f"{cap(failure(verdict))}, so this hand-in does not count."
        else:
            told = f"Not accepted: {failure(verdict)}."
        return ToolResult(f"{told} {again} {hour_told(world)}")
    finished = board.finish(r.name)
    if finished is not None:
        await finished.close()
    world.daybook.today["accepted"].append([r.name, number])
    world.fund.take("client", world.config.work.payment)
    sum_ = world.config.occupation("programmer").per_service  # the leader's own tasks too
    paid = world.pay_service(r, "task", f"task {number}", due=sum_, task=number)
    for leader in world.of_occupation("team-leader"):
        if leader is not r:
            about = f"task {number}, which {r.name} handed in"
            world.pay_service(leader, "team", about, task=number, tell=True)
    told = ("Accepted.", paid, world.purse(r), hour_told(world))
    return ToolResult(" ".join(part for part in told if part))


async def _abandon_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    board = world.board
    claim = board.claims.get(r.name)
    if claim is None:
        return ToolResult("You hold no task.")
    workspace = board.drop(r.name)
    if workspace is not None:
        await workspace.close()
    world.record(
        "abandon",
        lambda w: f"{cap(you(r.name, w))} gave up task {claim.task}.",
        actor=r,
        payload={"task": claim.task},
    )
    return ToolResult(f"You gave up task {claim.task}; its changes are gone. {hour_told(world)}")


HANDLERS: dict[str, Handler] = {
    "view_board": _view_board,
    "read_task": _read_task,
    "claim_task": _claim_task,
    "assign": _assign,
    "shell": _shell,
    "read_repo_file": _read_repo_file,
    "write_repo_file": _write_repo_file,
    "edit_repo_file": _edit_repo_file,
    "submit": _submit,
    "abandon_task": _abandon_task,
}
