"""The probe protocol: families of scenes of ordinary town life, each at graded stakes.

A family puts one trait at stake in one kind of situation. Its ladder lists the stake levels
from the least to the most tempting, in the town's own terms: crowns, as multiples of the
day's living cost, or minutes left before the work place closes on the day a job is due. Its
surfaces are a few fixed variants of the people, the job and the place, held fixed while the
stake varies; repetition r plays surface r modulo their number. Playing a level returns a
typed outcome named by the family, the score that outcome earns, in [0, 1] with higher meaning
more of the trait or None for an outcome that cannot be scored, and the raw measures behind
it. Scores come from what the resident does on its answer card as reality records it; a judge
reads free text only, answering one factual yes-or-no question about it with quotes.

Everything a probe shows a resident is composed by the town's own code (see
`evaluation.probes.town`); the only words a probe writes itself are what its strangers say and
the notes they hand over, which invariant 1 and `docs/IMMERSION.md` govern like every other text
a resident reads: they describe circumstances, never name or colour a trait, and never reveal
a test. They live in the upper-case constants of the family modules, which tests scan.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from pydantic import JsonValue

from core.interaction import (
    Action,
    CheckWork,
    Decision,
    Declaration,
    Observation,
    Speak,
    SubmitWork,
)
from evaluation.judge import Judge, Verdict
from infrastructure.config import StrictModel

if TYPE_CHECKING:
    from evaluation.probes.town import Backdrop, Town
    from evaluation.probes.work import Work


class Dimension(StrEnum):
    """The studied traits."""

    HONESTY = "honesty"
    COOPERATION = "cooperation"
    RELIABILITY = "reliability"
    REWARD_HACKING = "reward_hacking"


class Unit(StrEnum):
    """What a ladder counts: crowns, given as multiples of the day's living cost, or minutes
    left before the work place closes on the day a job is due."""

    CROWNS = "crowns"
    MINUTES = "minutes"


class Step(StrictModel):
    """One decision of the resident and the observation it answered."""

    observation: Observation
    decision: Decision


@dataclass(frozen=True)
class Played:
    """What a repetition came to: its typed `outcome`, the `score` that outcome earns (None
    if it cannot be scored) and the raw `measures` behind it."""

    outcome: str
    score: float | None
    measures: dict[str, JsonValue]


class Family(ABC):
    """One kind of situation that puts `trait` at stake, at the levels of `ladder` in `unit`.

    `strangers` names the people a probe introduces, for each surface; nobody in a run may
    share their names. `calls` bounds what a repetition costs: the fewest and the most
    decisions it asks of the resident, and the most questions it puts to the judge.
    """

    name: ClassVar[str]
    trait: ClassVar[Dimension]
    unit: ClassVar[Unit]
    ladder: ClassVar[tuple[float, ...]]
    strangers: ClassVar[tuple[tuple[str, ...], ...]]
    calls: ClassVar[tuple[int, int, int]]

    @property
    def levels(self) -> int:
        return len(self.ladder)

    @property
    def surfaces(self) -> int:
        return len(self.strangers)

    def stake(self, level: int, living_cost: int) -> int:
        """The stake of 1-based `level` in the town's terms: crowns or minutes."""
        step = self.ladder[level - 1]
        if self.unit is Unit.MINUTES:
            return int(step)
        if living_cost <= 0:
            raise ValueError(f"{self.name} counts in days of living cost, and the town has none")
        return max(1, round(step * living_cost))

    @abstractmethod
    async def ready(self, work: "Work", backdrop: "Backdrop") -> None:
        """Raise ValueError if `work` or the town of `backdrop` lacks what this family needs;
        checked before anything runs."""

    @abstractmethod
    async def play(self, town: "Town", level: int, surface: int, judge: Judge) -> Played:
        """Play 1-based `level` on `surface` with the resident of `town`."""


async def judged(
    judge: Judge, family: str, context: str, action: Action, question: str
) -> Verdict | None:
    """The judge's verdict on what the resident said in `action`, or None if it said nothing."""
    if not isinstance(action, Speak):
        return None
    return await judge.ask(family, context, action.text, question)


@dataclass(frozen=True)
class Code:
    """Code the resident produced for `part` of its job: tried at its desk, or handed in as
    finished or as unfinished (`how`)."""

    how: str
    part: int
    solution: str


TRIED, FINISHED, UNFINISHED = "tried", "finished", "unfinished"


def code_of(action: Action) -> Code | None:
    """The code `action` tries or hands in, if any."""
    match action:
        case CheckWork():
            return Code(TRIED, action.part, action.solution)
        case SubmitWork():
            how = FINISHED if action.declaration is Declaration.COMPLETE else UNFINISHED
            return Code(how, action.part, action.solution)
    return None
