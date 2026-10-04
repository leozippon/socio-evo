"""What an evaluation runs: the probes, how often, the judge model and the held-out work."""

from pathlib import Path
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, field_validator

from evaluation.probes import PROBES
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig

BANK = Path(__file__).with_name("bank")
"""The held-out coding task bank, disjoint from the simulation's."""

DEFAULT_CONFIG = Path(__file__).with_name("configs") / "default.yaml"


class EvaluationConfig(StrictModel):
    """The probes to run, each `repetitions` times on its own fresh export of the agent; the
    judge model that reads free text, configured apart from the evaluated agents' model; the
    held-out coding task bank, whose path may start with `~`, and the seconds each sandboxed
    check may take."""

    probes: tuple[Literal[tuple(PROBES)], ...] = Field(default=tuple(PROBES), min_length=1)
    repetitions: PositiveInt = 3
    judge: LLMConfig
    bank: Path = BANK
    sandbox_timeout: PositiveFloat = 5.0

    @field_validator("probes")
    @classmethod
    def _each_once(cls, probes: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(probes)) != len(probes):
            raise ValueError("each probe may be listed only once")
        return probes

    @field_validator("bank")
    @classmethod
    def _expanded(cls, bank: Path) -> Path:
        return bank.expanduser()
