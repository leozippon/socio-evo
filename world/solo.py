"""The world of the capability evaluation: one resident, one task, one Work event and no town.

`SoloPort` is the `agent.port.WorldPort` of a resident working alone on one task with the
town's work tools: the town's workspace tools (`world.tools.WORKSPACE_SPECS`: `shell` and the
reading, writing and editing of repository files) act in a workspace of the task, opened on
first use through the same `Backend` as the town's, and answer as the town's do, being the same
code; `submit` runs the official acceptance in a fresh container, at most `max_submissions`
times; `give_up` ends the work. There is no clock, place, purse or other resident. The resident is
told how the work goes in place of the town's rules, and the situation tells the task's
problem and repository, the minutes and turns left and the verdict of the last submission.

The task ends when a submission is accepted, when the last submission allowed is not, when the
resident gives up, when a budget is spent, or when the workspace or the acceptance fails: an
`error`, a failure of the machinery and never of the resident. The budgets are model requests
(the resident's turns), real time and tokens. The time is checked before every tool call and
every request; the calls of the reply that spends the last turn or the last tokens are still
carried out. Whoever meets the model for the resident awaits `turn` before each request, which
never returns once the task is over, and calls `spend` with the tokens of each reply. When the
task is over `done` is set and `wait` never returns: the runtime has nothing more to do, and
the caller cancels it and closes the port.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import PositiveFloat, PositiveInt

from agent.port import Percept, ToolResult, ToolSpec
from infrastructure.config import StrictModel
from world.backend import Backend, Task, Verdict, Workspace
from world.board import failure
from world.telling import counted
from world.tools import (
    WORKSPACE_SPECS,
    check,
    edit_repo,
    read_repo,
    spec,
    told_command,
    write_repo,
)

Ending = Literal["accepted", "rejected", "gave_up", "time", "requests", "usage", "error"]
"""How a task ended: accepted; the last submission allowed not accepted; given up; the budget
of time, of requests or of usage (`SoloConfig.max_tokens`) spent; or a failure of the
workspace or the acceptance."""

RULES = (
    "How this work goes.\n\n"
    "You have one task: a code repository with a problem to fix. Your workspace holds the "
    "repository; there you can run commands and read and write files, and it has no internet. "
    "When your change is ready, submit it: it is checked in a clean copy of the repository by "
    "checks you cannot see, and you are told whether it was accepted, and if not, what kind of "
    "failure it was and how many checks failed. You can submit at most {submissions}. You have "
    "{minutes} and {turns} for the task; each reply you make is one turn. Your work on the task "
    "ends when your change is accepted, when you have submitted as often as you can, when you "
    "give up, or when the time or the turns run out."
)
BEGUN = "Your work on the task begins."
TIME_PASSED = "Time passed."
OVER = "Your work on the task is over."
TIME_UP = "Your time for the task is up; your work on it is over."
BROKEN = "Your workspace stopped working; your work on the task is over."
GAVE_UP = "You gave up the task; your work on it is over."
ACCEPTED = "Accepted. Your work on the task is done."
NO_CHANGES = "Your workspace has no changes to hand in."


class SoloConfig(StrictModel):
    """The budgets of one task, the submissions it allows and the time limits of a command and
    of an acceptance, which should be the town's. A task may take `max_requests` model
    requests, `max_seconds` of real time and `max_tokens` tokens (prompt and completion of
    every request, as the server reports them: the budget of usage)."""

    max_requests: PositiveInt = 60
    max_seconds: PositiveFloat = 1800.0
    max_tokens: PositiveInt = 4_000_000
    max_submissions: PositiveInt = 2
    shell_timeout_s: PositiveInt = 300
    acceptance_timeout_s: PositiveInt = 1800


@dataclass(frozen=True)
class Submission:
    """A change handed in and the acceptance's verdict on it."""

    patch: str
    verdict: Verdict


class SoloPort:
    """One resident working alone on `task`; `name` names its workspace."""

    def __init__(self, task: Task, backend: Backend, config: SoloConfig, *, name: str) -> None:
        self.task = task
        self.config = config
        self.requests = 0
        self.tokens = 0
        self.submissions: list[Submission] = []
        self.ending: Ending | None = None
        self.error: str | None = None
        self.done = asyncio.Event()
        self._backend = backend
        self._name = name
        self._started = time.monotonic()
        self._workspace: Workspace | None = None
        self._interrupt = asyncio.Event()
        self._percepts = 0
        self._specs = _specs(config)
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[ToolResult]]] = {
            "shell": self._shell,
            "read_repo_file": self._read_repo_file,
            "write_repo_file": self._write_repo_file,
            "edit_repo_file": self._edit_repo_file,
            "submit": self._submit,
            "give_up": self._give_up,
        }

    # The port -------------------------------------------------------------------------------

    def rules(self) -> str:
        c = self.config
        return RULES.format(
            submissions=counted(c.max_submissions, "time"),
            minutes=counted(round(c.max_seconds / 60), "minute"),
            turns=counted(c.max_requests, "turn"),
        )

    def tool_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def situation(self) -> str:
        if self.ending is not None:
            return OVER
        c = self.config
        minutes = max(0, math.ceil((c.max_seconds - self.elapsed()) / 60))
        turns = max(0, c.max_requests - self.requests)
        parts = [
            f"You are at work on a task in {self.task.repo}.",
            f"You have {counted(minutes, 'minute')} and {counted(turns, 'turn')} left.",
        ]
        if self.submissions:
            left = c.max_submissions - len(self.submissions)
            parts.append(
                f"You have handed in your change {counted(len(self.submissions), 'time')}; the "
                f"last time it was not accepted: {failure(self.submissions[-1].verdict)}. You "
                f"can hand it in {counted(left, 'more time')}."
            )
        parts.append(f"Now you can use: {', '.join(self._specs)}.")
        return " ".join(parts) + f"\n\nThe problem:\n\n{self.task.problem_statement}"

    def sim_time(self) -> int:
        """Seconds since the task began."""
        return int(self.elapsed())

    def set_busy(self, busy: bool) -> None:
        pass

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self._specs[name]
        if self.ending is not None:
            return ToolResult(OVER, ends_turn=True)
        if self.elapsed() >= self.config.max_seconds:
            self.end("time")
            return ToolResult(TIME_UP, ends_turn=True)
        problem = check(spec, args)
        if problem:
            return ToolResult(problem)
        try:
            result = await self._handlers[name](args)
        except Exception as error:
            self.end("error", f"{name}: {type(error).__name__}: {error}")
            return ToolResult(BROKEN, ends_turn=True)
        if self.ending is None and self._spent() is not None:
            return ToolResult(result.text, ends_turn=True)
        return result

    def pending(self) -> list[Percept]:
        self._interrupt.clear()
        return []

    async def wait(self) -> list[Percept]:
        """The beginning of the work at the first call; later, after a reply without a tool
        call or with one that ended the turn, the passing of time while the task goes on."""
        if self._percepts == 0:
            return [self._percept(BEGUN, "start")]
        await self.turn()
        return [self._percept(TIME_PASSED, "time")]

    @property
    def interrupt(self) -> asyncio.Event:
        return self._interrupt

    # The budget and the end -----------------------------------------------------------------

    async def turn(self) -> None:
        """Return while the task goes on; end it if a budget is spent, and once it is over
        never return."""
        spent = self._spent()
        if self.ending is None and spent is not None:
            self.end(spent)
        if self.ending is not None:
            await asyncio.Event().wait()

    def spend(self, tokens: int) -> None:
        """Count one model request answered, which used `tokens` tokens."""
        self.requests += 1
        self.tokens += tokens

    def end(self, ending: Ending, error: str | None = None) -> None:
        """End the task, unless it is over already; `error` says what failed."""
        if self.ending is None:
            self.ending, self.error = ending, error
            self.done.set()

    def elapsed(self) -> float:
        """Real seconds since the task began."""
        return time.monotonic() - self._started

    async def close(self) -> None:
        """Close the workspace, if one was opened."""
        if self._workspace is not None:
            workspace, self._workspace = self._workspace, None
            await workspace.close()

    def _spent(self) -> Ending | None:
        c = self.config
        if self.elapsed() >= c.max_seconds:
            return "time"
        if self.requests >= c.max_requests:
            return "requests"
        if self.tokens >= c.max_tokens:
            return "usage"
        return None

    def _percept(self, text: str, kind: str) -> Percept:
        self._percepts += 1
        return Percept(text, kind, self._percepts, self.sim_time(), time.time())

    # The tools ------------------------------------------------------------------------------

    async def _open(self) -> Workspace:
        if self._workspace is None:
            self._workspace = await self._backend.open(self.task, self._name)
        return self._workspace

    async def _shell(self, args: dict[str, Any]) -> ToolResult:
        workspace = await self._open()
        timeout = self.config.shell_timeout_s
        return ToolResult(told_command(await workspace.exec(args["command"], timeout), timeout))

    async def _read_repo_file(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult((await read_repo(await self._open(), args))[0])

    async def _write_repo_file(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult((await write_repo(await self._open(), args))[0])

    async def _edit_repo_file(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult((await edit_repo(await self._open(), args))[0])

    async def _submit(self, args: dict[str, Any]) -> ToolResult:
        workspace = await self._open()
        patch = await workspace.diff()
        if not patch.strip():
            return ToolResult(NO_CHANGES)
        verdict = await self._backend.accept(self.task, patch, self.config.acceptance_timeout_s)
        self.submissions.append(Submission(patch, verdict))
        if verdict.resolved:
            self.end("accepted")
            return ToolResult(ACCEPTED, ends_turn=True)
        left = self.config.max_submissions - len(self.submissions)
        if left > 0:
            return ToolResult(
                f"Not accepted: {failure(verdict)}. You can hand it in "
                f"{counted(left, 'more time')}."
            )
        self.end("rejected")
        return ToolResult(
            f"Not accepted: {failure(verdict)}. You cannot hand it in again; your work on the "
            "task is over.",
            ends_turn=True,
        )

    async def _give_up(self, args: dict[str, Any]) -> ToolResult:
        self.end("gave_up")
        return ToolResult(GAVE_UP, ends_turn=True)


def _specs(config: SoloConfig) -> dict[str, ToolSpec]:
    """The work tools by name, in their declared order: the town's workspace tools, then
    submitting and giving up as they go here."""
    tools = [
        *WORKSPACE_SPECS,
        spec("submit", "Hand in your changes to the repository for checking. You are told "
             "whether they were accepted, and if not, what kind of failure it was and how many "
             "checks failed. The task can be handed in at most "
             f"{counted(config.max_submissions, 'time')}."),
        spec("give_up", "Give up the task: your work on it ends here, and nothing more of it "
             "is checked."),
    ]  # fmt: skip
    return {tool.name: tool for tool in tools}
