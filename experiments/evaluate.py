"""Evaluate a run: held-out probes on its agents as they stood at the end of given days.

    python -m experiments.evaluate RUN_DIR --days 0 3 [--config CONFIG] [--overwrite]

The agents answer through the model frozen in the run's configuration, or the dry-run
responder if the run is a dry run, and free text is judged by the model of the evaluation
configuration (by default `evaluation/configs/default.yaml`). Every model call of the
evaluation is recorded in the run's `evaluation/llm_calls.jsonl`, apart from the run's own.
One result file is written per agent and day, existing ones only with `--overwrite`, and the
scores of the evaluated days are printed as a table.
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from evaluation import DEFAULT_CONFIG, EvaluationConfig, ScoreRow, evaluate, read_scores
from experiments.config import ExperimentConfig
from experiments.dry_run import DryRunResponder
from infrastructure.config import load_config
from infrastructure.llm import RecordingClient, create_client
from infrastructure.storage import RunDirectory

COLUMNS = ("agent", "day", "dimension", "probe", "score")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.evaluate",
        description="Run the held-out probes on a run's agents at the end of given days.",
    )
    parser.add_argument("run", type=Path, help="run directory")
    parser.add_argument("--days", type=int, nargs="+", required=True, help="0 is the start")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="evaluation YAML")
    parser.add_argument("--overwrite", action="store_true", help="replace existing results")
    args = parser.parse_args(argv)

    run = RunDirectory.open(args.run)
    experiment = load_config(run.config_path, ExperimentConfig)
    config = load_config(args.config, EvaluationConfig)
    dry = experiment.llm.backend == "scripted"
    responder = DryRunResponder(experiment, run.read_manifest().seed) if dry else None
    calls = run.evaluation_calls_path
    asyncio.run(
        evaluate(
            run,
            args.days,
            config,
            client=RecordingClient(create_client(experiment.llm, responder), calls),
            judge=RecordingClient(create_client(config.judge), calls),
            cognition=experiment.cognition,
            overwrite=args.overwrite,
        )
    )
    print(table([row for row in read_scores(run) if row.day in args.days]))


def table(rows: Sequence[ScoreRow]) -> str:
    """`rows` in aligned columns; a score of None shows as `-`."""
    lines = [COLUMNS] + [
        (row.agent, str(row.day), row.dimension, row.probe, _score(row.score)) for row in rows
    ]
    widths = [max(len(line[column]) for line in lines) for column in range(len(COLUMNS))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in lines
    )


def _score(score: float | None) -> str:
    return "-" if score is None else f"{score:.2f}"


if __name__ == "__main__":
    main()
