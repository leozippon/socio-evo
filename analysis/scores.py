"""Held-out evaluation scores as tidy rows, with the raw measures behind them."""

from dataclasses import dataclass
from typing import Any

from evaluation.results import AgentResult
from infrastructure.storage import RunDirectory


@dataclass(frozen=True)
class Score:
    """One probe run on one agent as it stood at the end of `day` (0: as created)."""

    agent: str
    day: int
    commit: str
    """The agent version evaluated."""
    probe: str
    dimension: str
    """The trait the probe measures: `honesty`, `cooperation`, `reliability` or
    `reward_hacking`."""
    score: float | None
    """Mean over the repetitions that could be scored, from 0 to 1, higher meaning more of
    the trait; None if none could."""
    measures: dict[str, float]
    """Mean of each numeric or boolean raw measure over the repetitions that recorded it."""
    repetitions: list[dict[str, Any]]
    """Each repetition's `score` and raw `measures`, as the probe recorded them."""


def results(run: RunDirectory) -> dict[str, AgentResult]:
    """Every evaluation result of `run` by `<label>/<agent>`, in that order."""
    paths = sorted(run.evaluation_dir.glob("*/*.json"))
    return {
        f"{path.parent.name}/{path.stem}": AgentResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        for path in paths
    }


def scores(found: dict[str, AgentResult]) -> list[Score]:
    """One row per agent, evaluated day and probe of the results `found`, ordered so."""
    rows = [
        Score(
            agent=result.agent,
            day=result.day,
            commit=result.commit,
            probe=name,
            dimension=str(probe.dimension),
            score=probe.score,
            measures=probe.measures,
            repetitions=[
                {"score": outcome.score, "measures": outcome.measures}
                for outcome in probe.repetitions
            ],
        )
        for result in found.values()
        for name, probe in result.probes.items()
    ]
    return sorted(rows, key=lambda row: (row.agent, row.day, row.probe))
