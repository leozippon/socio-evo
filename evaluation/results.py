"""Result files, one per agent and evaluated day, and the tidy scores read back from them."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from pydantic import NonNegativeInt

from evaluation.probes import Dimension, Outcome, Score
from infrastructure.config import StrictModel
from infrastructure.storage import RunDirectory


class ProbeResult(StrictModel):
    """A probe's repetitions and their aggregates: `score` is the mean of the repetition
    scores that are not None, or None if all are; `measures` holds the mean of each measure
    whose values other than None are numbers or booleans, if it has any."""

    dimension: Dimension
    score: Score | None
    measures: dict[str, float]
    repetitions: tuple[Outcome, ...]

    @classmethod
    def of(cls, dimension: Dimension, repetitions: Sequence[Outcome]) -> "ProbeResult":
        scores = [outcome.score for outcome in repetitions if outcome.score is not None]
        measures = {}
        for key in dict.fromkeys(key for outcome in repetitions for key in outcome.measures):
            values = [o.measures[key] for o in repetitions if o.measures.get(key) is not None]
            if values and all(isinstance(value, bool | int | float) for value in values):
                measures[key] = fmean(values)
        return cls(
            dimension=dimension,
            score=fmean(scores) if scores else None,
            measures=measures,
            repetitions=tuple(repetitions),
        )


class AgentResult(StrictModel):
    """Every probe run on one agent as it stood at the end of `day`, at `commit`."""

    agent: str
    day: NonNegativeInt
    commit: str
    probes: dict[str, ProbeResult]


@dataclass(frozen=True)
class ScoreRow:
    agent: str
    day: int
    dimension: Dimension
    probe: str
    score: float | None


def label(day: int) -> str:
    """The evaluation label of `day`."""
    return f"day-{day:04d}"


def result_path(run: RunDirectory, agent: str, day: int) -> Path:
    return run.evaluation_path(label(day), agent)


def write_result(run: RunDirectory, result: AgentResult, *, overwrite: bool) -> Path:
    """Write `result` to its file and return the path; raises FileExistsError if the file
    exists, unless `overwrite`."""
    path = result_path(run, result.agent, result.day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as file:
        file.write(result.model_dump_json(indent=2) + "\n")
    return path


def read_scores(run: RunDirectory) -> list[ScoreRow]:
    """One row per agent, day and probe from every result file of `run`, ordered by agent,
    day and probe, for trajectory analysis."""
    rows = []
    for path in run.evaluation_dir.glob("*/*.json"):
        result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
        rows += [
            ScoreRow(result.agent, result.day, probe.dimension, name, probe.score)
            for name, probe in result.probes.items()
        ]
    return sorted(rows, key=lambda row: (row.agent, row.day, row.probe))
