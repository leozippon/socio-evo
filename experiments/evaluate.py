"""Evaluate a run: held-out probe families on its residents as they stood at the end of days.

    python -m experiments.evaluate RUN_DIR --days 0 3 [--config CONFIG] [--traits T ...]
        [--families F ...] [--levels L ...] [--repetitions N] [--variants V ...] [--overwrite]

The residents answer through the model frozen in the run's configuration, or the dry-run
responder if the run is a dry run, and free text is judged by the model of the evaluation
configuration (by default `evaluation/configs/default.yaml`), whose selection the options
narrow or change: `--traits` keeps the configured families of those traits. Before anything
runs, the number of scenes and the bounds on model calls are printed. Every model call of the
evaluation is recorded in the run's `evaluation/llm_calls.jsonl`, apart from the run's own.
One result file is written per resident, day and variant, existing ones only with
`--overwrite`, and each family's score, curve over its levels and switching level are printed.
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from evaluation import (
    DEFAULT_CONFIG,
    FAMILIES,
    AgentResult,
    EvaluationConfig,
    Variant,
    estimate,
    evaluate,
    read_results,
)
from experiments.config import ExperimentConfig
from experiments.run import agent_client
from infrastructure.config import load_config
from infrastructure.llm import RecordingClient, create_client
from infrastructure.storage import RunDirectory

COLUMNS = ("agent", "day", "variant", "trait", "family", "score", "curve", "switch")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.evaluate",
        description="Play the held-out probe families with a run's residents at given days.",
    )
    parser.add_argument("run", type=Path, help="run directory")
    parser.add_argument("--days", type=int, nargs="+", required=True, help="0 is the start")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="evaluation YAML")
    parser.add_argument("--traits", nargs="+", help="keep the families of these traits")
    parser.add_argument("--families", nargs="+", help="instead of the configured families")
    parser.add_argument("--levels", type=int, nargs="+", help="stake levels, from 1")
    parser.add_argument("--repetitions", type=int, help="repetitions of each level")
    parser.add_argument("--variants", nargs="+", choices=[str(v) for v in Variant])
    parser.add_argument("--overwrite", action="store_true", help="replace existing results")
    args = parser.parse_args(argv)

    run = RunDirectory.open(args.run)
    experiment = load_config(run.config_path, ExperimentConfig)
    config = selected(load_config(args.config, EvaluationConfig), args)
    residents = len(list(run.agents_dir.iterdir()))
    cost = estimate(config, residents, len(set(args.days)))
    print(
        f"{cost.scenes} scenes: between {cost.fewest} and {cost.most} decisions of the "
        f"residents' model and at most {cost.judged} questions to the judge."
    )
    calls = run.evaluation_calls_path
    asyncio.run(
        evaluate(
            run,
            args.days,
            config,
            client=RecordingClient(agent_client(experiment, run.read_manifest().seed), calls),
            judge=RecordingClient(create_client(config.judge), calls),
            cognition=experiment.cognition,
            environment=experiment.environment,
            simulation=experiment.simulation,
            overwrite=args.overwrite,
        )
    )
    variants = {str(variant) for variant in config.variants}
    print(
        table(
            [
                result
                for result in read_results(run)
                if result.day in args.days and str(result.variant) in variants
            ]
        )
    )


def selected(config: EvaluationConfig, args: argparse.Namespace) -> EvaluationConfig:
    """`config` with the selection the options make."""
    changes = {
        key: value
        for key, value in (
            ("families", args.families),
            ("levels", args.levels),
            ("repetitions", args.repetitions),
            ("variants", args.variants),
        )
        if value is not None
    }
    data = {**config.model_dump(), **changes}
    if args.traits:
        data["families"] = [n for n in data["families"] if FAMILIES[n].trait in args.traits]
    return EvaluationConfig.model_validate(data)


def table(results: Sequence[AgentResult]) -> str:
    """Each family of `results` in aligned columns: its score, its curve (the mean score at each
    level played, `-` where none was scored) and its switching level (`-` if none)."""
    lines = [COLUMNS]
    for result in results:
        for name, probe in result.probes.items():
            curve = " ".join(_score(value) for value in probe.curve.values())
            lines.append(
                (
                    result.agent,
                    str(result.day),
                    str(result.variant),
                    str(probe.dimension),
                    name,
                    _score(probe.score),
                    curve,
                    "-" if probe.switch is None else str(probe.switch),
                )
            )
    widths = [max(len(line[column]) for line in lines) for column in range(len(COLUMNS))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in lines
    )


def _score(score: float | None) -> str:
    return "-" if score is None else f"{score:.2f}"


if __name__ == "__main__":
    main()
