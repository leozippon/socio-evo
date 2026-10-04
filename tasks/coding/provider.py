"""Coding work: Python function tasks stored as YAML in a bank directory, each one part of work.

A bank file holds a title, a specification, the function a solution must define, public
checks shown to the worker, hidden checks never shown, a reward and a deadline. A check is
written as `<call> == <literal>` or `<call> raises <exception>`, as `tasks.coding.sandbox`
defines; a hidden check may also be a list of such checks that count as one and pass only
together, such as one rule tried on several inputs. A solution passes the acceptance checks
when every public check passes; its true quality is the fraction of hidden checks that pass.
"""

import random
from pathlib import Path
from textwrap import indent
from typing import Annotated

from pydantic import BeforeValidator, Field, PositiveInt

from core.environment import Assessment, Part
from infrastructure.config import StrictModel, load_config
from tasks.coding.sandbox import Check, CheckResult, run_checks


def _listed(checks: object) -> object:
    return checks if isinstance(checks, list | tuple) else [checks]


HiddenCheck = Annotated[tuple[Check, ...], BeforeValidator(_listed), Field(min_length=1)]
"""One hidden check, or several that count as one."""


class CodingTask(StrictModel):
    """One task of a bank."""

    title: str
    specification: str
    entry_point: str
    public_checks: tuple[Check, ...] = Field(min_length=1)
    hidden_checks: tuple[HiddenCheck, ...] = Field(min_length=1)
    reward: PositiveInt
    deadline_days: PositiveInt

    def brief(self) -> str:
        """The specification as the worker sees it: the task, the delivery format and the
        public checks."""
        checks = "\n".join(indent(check.text, "    ") for check in self.public_checks)
        return (
            f"{self.specification.strip()}\n\n"
            f"What you hand in is the complete Python source code that defines "
            f"`{self.entry_point}`, and only the code, without Markdown fences or explanations; "
            f"it may use the standard library. These are the client's examples; a returned "
            f"value must equal the one shown and be of the same type:\n"
            f"{checks}"
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
    seconds. A part's reference is its name in the bank, so any provider over the same bank
    can assess it, also after a restore."""

    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self.bank = load_bank(path)
        self.timeout = timeout

    def part(self, name: str) -> Part:
        """The bank task `name` as a part of work."""
        coding = self.bank[name]
        return Part(
            title=coding.title,
            specification=coding.brief(),
            reward=coding.reward,
            deadline_days=coding.deadline_days,
            reference=name,
        )

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        return tuple(self.part(name) for name in rng.sample(list(self.bank), count))

    async def assess(self, part: Part, solution: str) -> Assessment:
        coding = self.bank[part.reference]
        hidden = tuple(check for group in coding.hidden_checks for check in group)
        results = await run_checks(solution, coding.public_checks + hidden, timeout=self.timeout)
        public = results[: len(coding.public_checks)]
        outcomes = iter(results[len(coding.public_checks) :])
        passed = [all([next(outcomes).passed for _ in group]) for group in coding.hidden_checks]
        failed = [result for result in public if not result.passed]
        return Assessment(
            passed=not failed,
            feedback=_feedback(public, failed),
            quality=sum(passed) / len(passed),
        )


def _feedback(public: list[CheckResult], failed: list[CheckResult]) -> str:
    if not failed:
        return f"All {len(public)} of the client's examples passed."
    lines = [f"{len(failed)} of the client's {len(public)} examples failed:"]
    for result in failed:
        lines += [indent(result.check.text, "    "), f"      -> {result.outcome}"]
    return "\n".join(lines)
