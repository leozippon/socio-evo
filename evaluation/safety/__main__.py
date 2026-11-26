"""Put the safety instruments to residents' adapters or to a bare served model.

    python -m evaluation.safety --run RUN --day N [--resident NAME ...] [options]
    python -m evaluation.safety --run RUN --model NAME [--server SERVER.yaml] [options]

    options: [--guard GUARD.yaml] [--results DIR] [--concurrency N]

The subjects are named as `evaluation.command` says; GUARD is the judge's LLMConfig (by default
`evaluation/safety/guard.yaml`). Each subject's result is RESULTS/RUN/day-NN/safety/RESIDENT.json,
or RESULTS/models/safety/MODEL.json for a bare model, with every item's record beside it in
`.jsonl`: its key, instrument, id and template, its prompt's hash, the answer with any reasoning,
and the verdict with the judge's reply. A finished result is kept and a running one resumed
(`evaluation.results`).
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import evaluation.safety.guard as rules
import evaluation.safety.run as tallying
from evaluation.command import add_arguments, evaluate_each, share, subjects_of
from evaluation.results import Store, digest
from evaluation.safety.guard import CONFIG, Guard, identity
from evaluation.safety.items import INSTRUMENTS, SOURCES, Item, items_hash, load_items
from evaluation.safety.run import Record, evaluate_safety, metrics, pending
from evaluation.subject import Run, Subject, asking
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMConfig, LLMConfigError, create_client
from infrastructure.storage import read_jsonl

BENCHMARK = "safety"


def header(subject: Subject, run: Run, judge: LLMConfig, items: Sequence[Item]) -> dict[str, Any]:
    """What decides a subject's answers and their verdicts, as its result records it: the
    judge's reading rules and the tally by the digest of the files that hold them, the items by
    their hash, which holds every template's text."""
    return {
        "benchmark": BENCHMARK,
        "subject": subject.model_dump(mode="json"),
        "asked": asking(run),
        "judge": identity(judge)
        | {"rules": digest(Path(rules.__file__), Path(tallying.__file__))},
        "items": {
            "count": len(items),
            "hash": items_hash(items),
            "datasets": [source.model_dump() for source in SOURCES],
        },
    }


def told(found: dict[str, Any]) -> str:
    return ", ".join(
        f"{name} {share(found[name]['share'])} of {found[name]['denominator']} "
        f"({found[name]['counts']['empty']} empty, {found[name]['tool_calls']} with a tool call, "
        f"{found[name]['counts']['unjudged']} unjudged)"
        for name in INSTRUMENTS
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.safety", description=__doc__.split("\n\n")[0]
    )
    add_arguments(parser)
    parser.add_argument("--guard", type=Path, default=CONFIG, help="the judge's LLMConfig YAML")
    args = parser.parse_args(argv)
    run, server, subjects = subjects_of(args, parser)
    try:
        judge = load_config(args.guard, LLMConfig)
        client, guard = create_client(server), Guard(create_client(judge))
    except (FileNotFoundError, ConfigError, LLMConfigError) as error:
        parser.error(str(error))
    items = load_items()

    async def evaluate(model: str, store: Store, kept: list[dict[str, Any]]) -> dict[str, Any]:
        def keep(record: Record) -> None:
            store.add(record.model_dump(mode="json"))

        await evaluate_safety(pending(items, kept), client, model, run.reasoning, guard, keep)
        return metrics([Record.model_validate(record) for record in read_jsonl(store.records)])

    asyncio.run(
        evaluate_each(
            run,
            subjects,
            server,
            args.results,
            BENCHMARK,
            lambda subject: header(subject, run, judge, items),
            evaluate,
            told,
        )
    )


if __name__ == "__main__":
    main()
