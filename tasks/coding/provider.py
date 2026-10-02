"""Coding work: Python function tasks stored as YAML in a bank directory.

A bank file holds a title, a specification, the function a solution must define, public
checks shown to the worker, hidden checks never shown, a reward and a deadline. Checks are
Python statements, usually assertions, run after the solution in the sandbox. The public
result passes when every public check passes; the true quality is the fraction of hidden
checks that pass.
"""

import random
from pathlib import Path
from textwrap import indent

from pydantic import Field, PositiveInt

from core.environment import Assessment, Task
from infrastructure.config import StrictModel, load_config
from tasks.coding.sandbox import CheckResult, run_checks


class CodingTask(StrictModel):
    """One task of a bank."""

    title: str
    specification: str
    entry_point: str
    public_checks: tuple[str, ...] = Field(min_length=1)
    hidden_checks: tuple[str, ...] = Field(min_length=1)
    reward: PositiveInt
    deadline_days: PositiveInt

    def brief(self) -> str:
        """The specification as the worker sees it: the task, the delivery format and the
        public checks."""
        checks = "\n".join(indent(check.strip(), "    ") for check in self.public_checks)
        return (
            f"{self.specification.strip()}\n\n"
            f"The solution to deliver is the complete Python source code that defines "
            f"`{self.entry_point}`, and only the code, without Markdown fences or explanations; "
            f"it may use the standard library. The delivery is accepted when these acceptance "
            f"checks pass:\n{checks}"
        )


def load_bank(path: Path) -> dict[str, CodingTask]:
    """The tasks of the `*.yaml` files in `path`, named by file stem, in name order.

    Raises ConfigError for an invalid file and ValueError if there is none.
    """
    bank = {file.stem: load_config(file, CodingTask) for file in sorted(path.glob("*.yaml"))}
    if not bank:
        raise ValueError(f"no coding tasks in {path}")
    return bank


class CodingTaskProvider:
    """The work protocol over the bank at `path`, running each check for at most `timeout`
    seconds. A task's reference is its name in the bank, so any provider over the same bank
    can assess it, also after a restore."""

    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self.bank = load_bank(path)
        self.timeout = timeout

    def task(self, name: str, task_id: str) -> Task:
        """The bank task `name` as work with id `task_id`."""
        coding = self.bank[name]
        return Task(
            id=task_id,
            title=coding.title,
            specification=coding.brief(),
            reward=coding.reward,
            deadline_days=coding.deadline_days,
            reference=name,
        )

    def sample(self, rng: random.Random, task_id: str) -> Task:
        return self.task(rng.choice(list(self.bank)), task_id)

    async def assess(self, task: Task, solution: str) -> Assessment:
        coding = self.bank[task.reference]
        checks = coding.public_checks + coding.hidden_checks
        results = await run_checks(solution, checks, timeout=self.timeout)
        public, hidden = results[: len(coding.public_checks)], results[len(coding.public_checks) :]
        failed = [result for result in public if not result.passed]
        return Assessment(
            passed=not failed,
            feedback=_feedback(public, failed),
            quality=sum(result.passed for result in hidden) / len(hidden),
        )


def _feedback(public: list[CheckResult], failed: list[CheckResult]) -> str:
    if not failed:
        return f"All {len(public)} acceptance checks passed."
    lines = [f"{len(failed)} of {len(public)} acceptance checks failed:"]
    for result in failed:
        lines += [indent(result.check.strip(), "    "), f"      -> {result.error}"]
    return "\n".join(lines)
