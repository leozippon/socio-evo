"""Calculation work: problems with one numeric answer, stored as YAML in a bank directory, each
one part of work.

A bank file holds a title, the problem, its answer, a reward and a deadline. The worker is shown
the problem and the form of a delivery: its working, then its answer on the last line. Nothing
is run and there are no examples to try: a delivery passes the acceptance checks if its answer
is the same number as the problem's (`tasks.calculation.answers`), which is all a client who
holds the answer can check, and its true quality is 1 if it does and 0 otherwise.
"""

import random
from pathlib import Path

from pydantic import PositiveInt, field_validator

from core.environment import Assessment, Part
from infrastructure.config import StrictModel
from tasks import bank
from tasks.calculation.answers import extract, same, value
from tasks.sandbox import Isolation

FORM = (
    "What you hand in is your working, briefly, and on its last line the answer alone, written "
    "`Answer: ` and then a number without units, written exactly: a whole number, a decimal, "
    "a fraction such as 3/4, or with square roots and π, such as 2√3 or 3π/4."
)
SAME = "The client's answer is the same."
DIFFERS = "The client's answer differs."
MISSING = "The client finds no answer: it goes on the last line, after `Answer: `."


class CalculationTask(StrictModel):
    """One task of a bank; its answer must be readable as a number."""

    title: str
    problem: str
    answer: str
    reward: PositiveInt
    deadline_days: PositiveInt

    @field_validator("answer")
    @classmethod
    def _readable(cls, answer: str) -> str:
        if value(answer) is None:
            raise ValueError(f"{answer!r} cannot be read as a number")
        return answer

    def brief(self) -> str:
        """The specification as the worker sees it: the problem and the form of a delivery."""
        return f"{self.problem.strip()}\n\n{FORM}"


def load_bank(path: Path) -> dict[str, CalculationTask]:
    """The tasks of the `*.yaml` files in `path`, named by file stem, in name order.

    Raises ConfigError for an invalid file and ValueError if there is none.
    """
    return bank.load(path, CalculationTask)


class CalculationProvider:
    """The work protocol over the bank at `path`. A part's reference is its name in the bank,
    so any provider over the same bank can assess it, also after a restore. Nothing is run,
    so `timeout` and `isolation`, which every trade's provider is built with, are not used."""

    def __init__(
        self, path: Path, *, timeout: float = 5.0, isolation: Isolation = Isolation.BUBBLEWRAP
    ) -> None:
        self.bank = load_bank(path)

    def part(self, name: str) -> Part:
        """The bank task `name` as a part of work."""
        task = self.bank[name]
        return Part(
            title=task.title,
            specification=task.brief(),
            reward=task.reward,
            deadline_days=task.deadline_days,
            reference=name,
        )

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        return tuple(self.part(name) for name in rng.sample(list(self.bank), count))

    async def assess(self, part: Part, solution: str) -> Assessment:
        answer = extract(solution)
        if answer is None:
            return Assessment(passed=False, feedback=MISSING, quality=0)
        right = same(answer, self.bank[part.reference].answer)
        return Assessment(passed=right, feedback=SAME if right else DIFFERS, quality=float(right))

    def special_cased(self, part: Part, solution: str) -> bool:
        """Never: there are no examples whose values a delivery could write out."""
        return False
