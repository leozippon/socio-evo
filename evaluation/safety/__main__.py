"""Put the safety instruments to residents' adapters or to a bare served model.

    python -m evaluation.safety --run RUN --day N [--resident NAME ...] [options]
    python -m evaluation.safety --run RUN --model NAME [--server SERVER.yaml] [options]

    options: [--guard GUARD.yaml] [--results DIR] [--concurrency N] [--instruments NAME ...]
             [--persona RESIDENT]

The subjects are named as `evaluation.command` says; GUARD is the judge's LLMConfig (by default
`evaluation/safety/guard.yaml`). Each subject's result is RESULTS/RUN/day-NN/safety/RESIDENT.json,
or RESULTS/models/safety/MODEL.json for a bare model, with every item's record beside it in
`.jsonl`: its key, instrument, id and template, its prompt's hash, the answer with any reasoning,
and the verdict with the judge's reply. A finished result is kept and a running one resumed
(`evaluation.results`).

`--instruments` scores only those named. Such a result is not a full one and is never taken for
one: its benchmark is `safety-<instrument>-...` (in the order of `INSTRUMENTS`), so that it lies
apart from the full results, where nothing that reads them looks, its header names the
instruments beside its items, and its metrics hold those instruments alone. Naming all three is
the full evaluation.

`--persona RESIDENT` breaks the subject's plain conversation on purpose, for a calibration and
never for an outcome: every item follows a system message that is that resident's background
as the run's configuration names it, headed as the town heads it (`agent.texts.ABOUT_ME`), and
nothing else of the town. Its result lies apart, under `<benchmark>-persona-<resident>`, and its
header names the resident and the system message by its hash.
"""

import argparse
import asyncio
import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import evaluation.safety.guard as rules
import evaluation.safety.run as tallying
from agent.texts import ABOUT_ME
from evaluation.command import add_arguments, evaluate_each, share, subjects_of
from evaluation.results import Store, digest
from evaluation.safety.guard import CONFIG, Guard, identity
from evaluation.safety.items import (
    INSTRUMENTS,
    SOURCES,
    Instrument,
    Item,
    items_hash,
    load_items,
)
from evaluation.safety.readings import lower_share
from evaluation.safety.run import Record, evaluate_safety, metrics, pending
from evaluation.subject import Run, Subject, asking
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMConfig, LLMConfigError, create_client
from infrastructure.storage import read_jsonl
from simulation.config import PROJECT_ROOT

BENCHMARK = "safety"


def header(
    subject: Subject,
    run: Run,
    judge: LLMConfig,
    items: Sequence[Item],
    instruments: Sequence[Instrument] = INSTRUMENTS,
    persona: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """What decides a subject's answers and their verdicts, as its result records it: the
    judge's reading rules and the tally by the digest of the files that hold them, the items by
    their hash, which holds every template's text, when they are of some of the instruments
    alone, which, and the `persona` (its resident and system message) they were asked in."""
    some = {} if tuple(instruments) == INSTRUMENTS else {"instruments": list(instruments)}
    asked_as = {}
    if persona is not None:
        system = hashlib.sha256(persona[1].encode()).hexdigest()
        asked_as = {"persona": {"resident": persona[0], "system": system}}
    return asked_as | {
        "benchmark": BENCHMARK,
        "subject": subject.model_dump(mode="json"),
        "asked": asking(run),
        "judge": identity(judge)
        | {"rules": digest(Path(rules.__file__), Path(tallying.__file__))},
        "items": {
            "count": len(items),
            "hash": items_hash(items),
            "datasets": [source.model_dump() for source in SOURCES],
        }
        | some,
    }


def benchmark(instruments: Sequence[Instrument], persona: str | None = None) -> str:
    """Where the results of `instruments` lie: `safety` for all, apart for some, and apart again
    when asked in the `persona` of a resident."""
    some = () if tuple(instruments) == INSTRUMENTS else tuple(instruments)
    asked_as = () if persona is None else ("persona", persona.lower())
    return "-".join((BENCHMARK, *some, *asked_as))


def persona_of(run: Run, resident: str) -> str:
    """The system message of `resident`'s persona: its background as `run` names it, headed as
    the town heads it. ValueError when the configuration names none."""
    if resident not in run.backgrounds:
        raise ValueError(f"{run.name} names no background for {resident}")
    background = (PROJECT_ROOT / run.backgrounds[resident]).read_text(encoding="utf-8")
    return f"{ABOUT_ME}\n\n{background.strip()}"


def told(found: dict[str, Any]) -> str:
    def lower(name: str) -> str:
        return "" if name == "harmless" else f" (Unsafe alone {share(lower_share(found[name]))})"

    return ", ".join(
        f"{name} {share(found[name]['share'])}{lower(name)} of {found[name]['denominator']} "
        f"({found[name]['counts']['empty']} empty, {found[name]['tool_calls']} with a tool call, "
        f"{found[name]['counts']['unjudged']} unjudged)"
        for name in INSTRUMENTS
        if name in found
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.safety", description=__doc__.split("\n\n")[0]
    )
    add_arguments(parser)
    parser.add_argument("--guard", type=Path, default=CONFIG, help="the judge's LLMConfig YAML")
    parser.add_argument(
        "--instruments",
        nargs="+",
        choices=INSTRUMENTS,
        default=list(INSTRUMENTS),
        help="only these instruments, a result apart from the full one (default: all three)",
    )
    parser.add_argument(
        "--persona", help="ask in this resident's background, a result apart from the plain one"
    )
    args = parser.parse_args(argv)
    instruments = tuple(name for name in INSTRUMENTS if name in args.instruments)
    run, server, subjects = subjects_of(args, parser)
    try:
        system = None if args.persona is None else persona_of(run, args.persona)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    persona = None if system is None else (args.persona, system)
    try:
        judge = load_config(args.guard, LLMConfig)
        client, guard = create_client(server), Guard(create_client(judge))
    except (FileNotFoundError, ConfigError, LLMConfigError) as error:
        parser.error(str(error))
    items = [item for item in load_items() if item.instrument in instruments]

    async def evaluate(model: str, store: Store, kept: list[dict[str, Any]]) -> dict[str, Any]:
        def keep(record: Record) -> None:
            store.add(record.model_dump(mode="json"))

        await evaluate_safety(
            pending(items, kept), client, model, run.reasoning, guard, keep, system
        )
        records = [Record.model_validate(record) for record in read_jsonl(store.records)]
        return metrics(records, instruments)

    asyncio.run(
        evaluate_each(
            run,
            subjects,
            server,
            args.results,
            benchmark(instruments, args.persona),
            lambda subject: header(subject, run, judge, items, instruments, persona),
            evaluate,
            told,
        )
    )


if __name__ == "__main__":
    main()
