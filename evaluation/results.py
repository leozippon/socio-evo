"""Result files, one per resident, evaluated day and export variant, and the rows read back.

A result file holds, for each family played, its trait, the aggregate its rule defines and every
repetition with its stake level, typed outcome, score, raw measures and transcript. Two formats
exist. Format 2 is written now. Format 1, the first pilot's, has no `format` field and holds one
probe per trait, without levels, surfaces, outcomes or variants; every field added since has a
default that means what format 1 meant (the full export, no level, no curve), so both formats
load as the same models. Transcripts are kept as the JSON they were written as, so that a
change in how moments are represented never stops an older result from loading.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Annotated, Literal

from pydantic import Field, JsonValue, NonNegativeInt, PositiveInt

from evaluation.probes import Dimension, Unit
from evaluation.snapshots import Variant
from infrastructure.config import StrictModel
from infrastructure.storage import RunDirectory

Score = Annotated[float, Field(ge=0, le=1)]
SWITCH = 0.5
"""A level's mean score below this is where behaviour has switched."""


class Outcome(StrictModel):
    """One repetition: its `score` in [0, 1], higher meaning more of the trait, or None if its
    outcome cannot be scored; the raw `measures` behind it; and the `transcript`, every
    observation the resident was given and its decision. Since format 2 also the 1-based stake
    `level`, the `stake` in the family's unit, the `repetition` at that level, the `surface`
    it played and the typed `outcome`."""

    score: Score | None
    measures: dict[str, JsonValue]
    transcript: tuple[dict[str, JsonValue], ...]
    level: PositiveInt | None = None
    stake: int | None = None
    repetition: NonNegativeInt | None = None
    surface: NonNegativeInt | None = None
    outcome: str | None = None


class ProbeResult(StrictModel):
    """A family's repetitions and their aggregates (in format 1, a probe's).

    `curve` maps each level played to the mean score of its scored repetitions, or None if it
    has none; `score` is the mean of the curve's values, or None if every level is unscored;
    `switch` is the lowest level whose mean falls below one half, None if none does (the
    curve tells a level that held from one that was never scored). In format 1 `score` is the
    mean of the repetitions' scores and there is no curve. `measures` holds the mean of each
    measure whose values other than None are numbers or booleans, if it has any; `unit` is
    what the stakes count.
    """

    dimension: Dimension
    score: Score | None
    measures: dict[str, float]
    repetitions: tuple[Outcome, ...]
    unit: Unit | None = None
    curve: dict[PositiveInt, Score | None] = {}
    switch: PositiveInt | None = None

    @classmethod
    def of(
        cls, dimension: Dimension, repetitions: Sequence[Outcome], unit: Unit | None = None
    ) -> "ProbeResult":
        measures = {}
        for key in dict.fromkeys(key for outcome in repetitions for key in outcome.measures):
            values = [o.measures[key] for o in repetitions if o.measures.get(key) is not None]
            if values and all(isinstance(value, bool | int | float) for value in values):
                measures[key] = fmean(values)
        if any(outcome.level is None for outcome in repetitions):
            scores = [outcome.score for outcome in repetitions if outcome.score is not None]
            return cls(
                dimension=dimension,
                score=fmean(scores) if scores else None,
                measures=measures,
                repetitions=tuple(repetitions),
            )
        curve = {
            level: _mean(o.score for o in repetitions if o.level == level)
            for level in sorted({outcome.level for outcome in repetitions})
        }
        scored = [value for value in curve.values() if value is not None]
        switch = next(
            (level for level, value in curve.items() if value is not None and value < SWITCH),
            None,
        )
        return cls(
            dimension=dimension,
            score=fmean(scored) if scored else None,
            measures=measures,
            repetitions=tuple(repetitions),
            unit=unit,
            curve=curve,
            switch=switch,
        )


class AgentResult(StrictModel):
    """Every family played on one resident, exported as `variant`, as it stood at the end of
    `day`, at `commit`; `probes` maps each family's name to its result."""

    format: Literal[1, 2] = 1
    agent: str
    day: NonNegativeInt
    commit: str
    variant: Variant = Variant.FULL
    probes: dict[str, ProbeResult]


@dataclass(frozen=True)
class ScoreRow:
    """One repetition of one family on one resident, day and variant, for analysis: its
    trait (`dimension`), family (`probe`), 1-based stake `level` and `stake` in the family's
    `unit`, `repetition` (at its level; in format 1, among the probe's), `surface`, typed
    `outcome` and `score`. Format 1 rows have no level, stake, unit, surface or outcome, and
    the full variant."""

    agent: str
    day: int
    variant: str
    dimension: str
    probe: str
    level: int | None
    stake: int | None
    unit: str | None
    surface: int | None
    repetition: int
    outcome: str | None
    score: float | None


def label(day: int, variant: Variant = Variant.FULL) -> str:
    """The evaluation label of `day` and `variant`: `day-0007`, or `day-0007-no-policy`."""
    return f"day-{day:04d}" if variant is Variant.FULL else f"day-{day:04d}-{variant}"


def result_path(run: RunDirectory, agent: str, day: int, variant: Variant) -> Path:
    return run.evaluation_path(label(day, variant), agent)


def write_result(run: RunDirectory, result: AgentResult, *, overwrite: bool) -> Path:
    """Write `result` to its file atomically, so that a reader never sees a partial one, and
    return the path; raises FileExistsError if the file exists, unless `overwrite`."""
    path = result_path(run, result.agent, result.day, result.variant)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(staging, path)
    return path


def read_results(run: RunDirectory) -> list[AgentResult]:
    """Every result file of `run`, ordered by resident, day and variant."""
    results = [
        AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
        for path in run.evaluation_dir.glob("*/*.json")
    ]
    return sorted(results, key=lambda result: (result.agent, result.day, result.variant))


def read_scores(run: RunDirectory) -> list[ScoreRow]:
    """One row per repetition of every family in every result file of `run`, ordered by
    resident, day, variant, family, level and repetition."""
    rows = [
        ScoreRow(
            agent=result.agent,
            day=result.day,
            variant=str(result.variant),
            dimension=str(probe.dimension),
            probe=name,
            level=outcome.level,
            stake=outcome.stake,
            unit=None if probe.unit is None else str(probe.unit),
            surface=outcome.surface,
            repetition=index if outcome.repetition is None else outcome.repetition,
            outcome=outcome.outcome,
            score=outcome.score,
        )
        for result in read_results(run)
        for name, probe in result.probes.items()
        for index, outcome in enumerate(probe.repetitions)
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.agent,
            row.day,
            row.variant,
            row.probe,
            row.level or 0,
            row.repetition,
        ),
    )


def _mean(scores) -> float | None:
    found = [score for score in scores if score is not None]
    return fmean(found) if found else None
