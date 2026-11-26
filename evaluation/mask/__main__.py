"""Put the fixed MASK scenarios to residents' adapters or to a bare served model.

    python -m evaluation.mask --run RUN --day N [--resident NAME ...] [options]
    python -m evaluation.mask --run RUN --model NAME [--server SERVER.yaml] [options]

    options: [--judge JUDGE.yaml] [--results DIR] [--concurrency N]

The subjects are named as `evaluation.command` says; JUDGE is the LLMConfig of the judge (by
default `evaluation/judge.yaml`). Each subject's result is RESULTS/RUN/day-NN/mask/RESIDENT.json,
or RESULTS/models/mask/MODEL.json for a bare model, with each scenario's prompts, replies and
verdicts beside it in `.jsonl`, and every call of the judge in `.judge.jsonl`. Its metrics are
the count of each outcome over the answers under pressure, the unjudged among them, and the share
of each over those judged, the share of lies first. A finished result is kept and a running one
resumed, scenario by scenario (`evaluation.results`).
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import evaluation.judge as prompts
import evaluation.mask.run as reading
from evaluation.command import add_arguments, evaluate_each, share, subjects_of
from evaluation.judge import CONFIG as JUDGE_CONFIG
from evaluation.judge import Judge
from evaluation.mask.dataset import REPO, REVISION, Scenario, load_scenarios
from evaluation.mask.run import (
    BELIEF_RUNS,
    OUTCOMES,
    PRESSURE_RUNS,
    MaskResult,
    ScenarioResult,
    evaluate_mask,
)
from evaluation.results import Store, digest
from evaluation.subject import Run, Subject, asking
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMConfig, LLMConfigError, create_client
from infrastructure.storage import read_jsonl

BENCHMARK = "mask"


def header(
    subject: Subject, run: Run, judge: LLMConfig, scenarios: Sequence[Scenario]
) -> dict[str, Any]:
    """What decides a subject's answers and their outcomes, as its result records it: the
    judge's prompts and the reading of its verdicts by the digest of the files that hold them,
    and each scenario's reviewed reading of a yes or no."""
    return {
        "benchmark": BENCHMARK,
        "subject": subject.model_dump(mode="json"),
        "asked": asking(run),
        "judge": {
            "model": judge.model,
            "prompts": digest(Path(prompts.__file__), Path(reading.__file__)),
        },
        "scenarios": {
            "repo": REPO,
            "revision": REVISION,
            "ids": [scenario.id for scenario in scenarios],
            "readings": {
                s.id: s.yes_no.model_dump() for s in scenarios if s.yes_no is not None
            },
            "belief_runs": BELIEF_RUNS,
            "pressure_runs": PRESSURE_RUNS,
        },
    }


def told(found: dict[str, Any]) -> str:
    shares = found["shares"] or {}
    judged = ", ".join(f"{name} {share(shares.get(name))}" for name in OUTCOMES)
    counts = found["counts"]
    return (
        f"{judged} of {found['denominator']} ({found['empty']} empty, {counts['unjudged']} "
        "unjudged)"
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.mask", description=__doc__.split("\n\n")[0]
    )
    add_arguments(parser)
    parser.add_argument("--judge", type=Path, default=JUDGE_CONFIG, help="judge LLMConfig YAML")
    args = parser.parse_args(argv)
    run, server, subjects = subjects_of(args, parser)
    try:
        judging = load_config(args.judge, LLMConfig)
        client, judged = create_client(server), create_client(judging)
    except (FileNotFoundError, ConfigError, LLMConfigError) as error:
        parser.error(str(error))
    scenarios = load_scenarios()

    async def evaluate(model: str, store: Store, kept: list[dict[str, Any]]) -> dict[str, Any]:
        done = {record["id"] for record in kept}
        judge = Judge(judged, store.path.with_suffix(".judge.jsonl"))

        def keep(result: ScenarioResult) -> None:
            store.add(result.model_dump(mode="json"))

        todo = [scenario for scenario in scenarios if scenario.id not in done]
        await evaluate_mask(client, model, judge, todo, keep, reasoning=run.reasoning)
        results = [ScenarioResult.model_validate(record) for record in read_jsonl(store.records)]
        return MaskResult.of(results).model_dump(mode="json")

    asyncio.run(
        evaluate_each(
            run,
            subjects,
            server,
            args.results,
            BENCHMARK,
            lambda subject: header(subject, run, judging, scenarios),
            evaluate,
            told,
        )
    )


if __name__ == "__main__":
    main()
