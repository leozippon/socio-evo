"""What an evaluation runs: the families, levels, repetitions and export variants, the judge
model, and the held-out work."""

from pathlib import Path
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator

from evaluation.probes import FAMILIES
from evaluation.snapshots import Variant
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig
from tasks.coding import Isolation

DEFAULT_CONFIG = Path(__file__).with_name("configs") / "default.yaml"
WORK = Path(__file__).with_name("work.yaml")
"""The jobs of the families' surfaces in the held-out banks."""

Family = Literal[tuple(FAMILIES)]


class EvaluationConfig(StrictModel):
    """The `families` to play, each at its stake `levels` (1-based, shared by every family,
    whose ladders all have four), each level `repetitions` times on its own fresh export of
    the resident, repetition r on the family's surface r modulo their number; the export
    `variants` to play them on; the `judge` model that reads free text, configured apart from
    the evaluated residents' model; and the held-out work: the `bank` root holding the
    held-out banks (it may start with `~`), the `work` file naming each surface's job, the
    seconds each sandboxed check may take and how checks are isolated (`tasks.coding.Isolation`;
    running without isolation is a named choice, never a fallback)."""

    families: tuple[Family, ...] = Field(default=tuple(FAMILIES), min_length=1)
    levels: tuple[Literal[1, 2, 3, 4], ...] = Field(default=(1, 2, 3, 4), min_length=1)
    repetitions: PositiveInt = 1
    variants: tuple[Variant, ...] = Field(default=(Variant.FULL,), min_length=1)
    judge: LLMConfig
    bank: Path
    work: Path = WORK
    sandbox_timeout: PositiveFloat = 5.0
    isolation: Isolation = Isolation.BUBBLEWRAP

    @field_validator("families", "levels", "variants")
    @classmethod
    def _each_once(cls, values: tuple) -> tuple:
        if len(set(values)) != len(values):
            raise ValueError("each may be listed only once")
        return values

    @field_validator("bank", "work")
    @classmethod
    def _expanded(cls, path: Path) -> Path:
        return path.expanduser()

    @model_validator(mode="after")
    def _ladders_fit(self) -> "EvaluationConfig":
        for name in self.families:
            if max(self.levels) > FAMILIES[name].levels:
                raise ValueError(f"{name} has only {FAMILIES[name].levels} levels")
        return self
