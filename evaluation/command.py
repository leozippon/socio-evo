"""What the two evaluation commands (`evaluation.safety`, `evaluation.mask`) share: naming the
subjects on the command line, serving each in turn and skipping, resuming or beginning its
result.

    --run RUN --day N [--resident NAME ...]   each resident's adapter at day N
    --run RUN --model NAME [--server YAML]    the bare served model NAME

A resident's subject is the run's base model with the adapter `learning.adapters.adapter_for`
gives for its day, the base alone when there is none yet. On day 0 every adapter is empty, so the
subject of `--day 0` is the base model alone, as a bare model, which stands for every resident.
The adapter is loaded on every replica under a name of its own for the length of its evaluation
and unloaded after, so that it meets no other use of the same adapter. A bare model is served by
the run's server unless `--server` names another (an LLMConfig YAML), as for the reference model.
A result is held by one process at a time; another that comes for it fails.
"""

import argparse
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from evaluation.results import MODELS, Store, model_result, resident_result
from evaluation.subject import Run, Subject
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMConfig
from infrastructure.llm.adapters import load_adapter, unload_adapter
from infrastructure.storage import day_tag
from learning.adapters import adapter_for

NAME = re.compile(r"[\w.-]+")
"""What a model's name must be to name its results' files."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run", type=Path, required=True, help="run directory (runs/RUN): its server and reasoning"
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--day", type=int, help="the residents' adapters at this day")
    which.add_argument("--model", help="a bare served model, by its served name")
    parser.add_argument(
        "--resident", action="append", default=[], help="with --day: only this one (repeatable)"
    )
    parser.add_argument(
        "--server",
        type=Path,
        help="with --model: LLMConfig YAML of its server (default: the run's)",
    )
    parser.add_argument(
        "--results", type=Path, default=Path("results"), help="results root (default: results)"
    )
    parser.add_argument(
        "--concurrency", type=int, help="requests in flight (default: the server configuration's)"
    )


def subjects_of(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[Run, LLMConfig, list[Subject]]:
    """The run, the server and the subjects the command line names; errors through `parser`."""
    try:
        run = Run.read(args.run)
        server = run.llm if args.server is None else load_config(args.server, LLMConfig)
    except (FileNotFoundError, ValueError, ConfigError) as error:
        parser.error(str(error))
    if run.name == MODELS:
        parser.error(f"a run named {MODELS} would share its results with the bare models")
    if args.concurrency is not None:
        if args.concurrency < 1:
            parser.error("--concurrency must be at least 1")
        server = server.model_copy(update={"max_concurrency": args.concurrency})
    if args.model is not None:
        if args.resident:
            parser.error("--resident names a resident of a day, not a bare model")
        if not NAME.fullmatch(args.model):
            parser.error(f"--model {args.model}: a served name of letters, digits, '.', '_', '-'")
        return run, server, [Subject(base=args.model)]
    if args.server is not None:
        parser.error("--server serves a bare model (--model) only")
    if args.day < 0:
        parser.error(f"day {args.day}: no such day")
    if args.day == 0:
        if args.resident:
            parser.error("on day 0 the base model stands for every resident: name none")
        return run, server, [Subject(base=run.llm.model)]
    if unknown := [name for name in args.resident if name not in run.residents]:
        parser.error(f"{', '.join(unknown)}: no resident of {run.name}")
    return (
        run,
        server,
        [
            Subject(
                base=run.llm.model,
                adapter=adapter_for(run.path, name, args.day),
                run=run.name,
                resident=name,
                day=args.day,
            )
            for name in args.resident or run.residents
        ],
    )


def result_of(results: Path, benchmark: str, subject: Subject) -> Path:
    if subject.resident is None:
        return model_result(results, benchmark, subject.base)
    assert subject.run is not None and subject.day is not None
    return resident_result(results, subject.run, subject.day, benchmark, subject.resident)


@asynccontextmanager
async def served(subject: Subject, server: LLMConfig) -> AsyncIterator[str]:
    """The model name to ask `subject` by: its base, or its adapter, loaded for as long as the
    context lasts under a name no other use of it has."""
    if subject.adapter is None:
        yield subject.base
        return
    assert subject.day is not None
    name = f"eval-{subject.run}-{subject.resident}-{day_tag(subject.day)}-{uuid.uuid4().hex[:8]}"
    await load_adapter(server, name, subject.adapter)
    try:
        yield name
    finally:
        await unload_adapter(server, name)


Evaluate = Callable[[str, Store, list[dict[str, Any]]], Awaitable[dict[str, Any]]]
"""Evaluates the served model by the name given, adds its records to the store beside those
kept so far, and returns the metrics of them all."""


async def evaluate_each(
    subjects: list[Subject],
    server: LLMConfig,
    results: Path,
    benchmark: str,
    header: Callable[[Subject], dict[str, Any]],
    evaluate: Evaluate,
    told: Callable[[dict[str, Any]], str],
) -> None:
    """Each subject in turn: a finished result told and kept, a running one resumed, and a new
    one begun; each serving of an adapter ends before the next begins. `told` says the metrics
    in a line."""
    for subject in subjects:
        store = Store(result_of(results, benchmark, subject))
        with store.held():
            if store.finished:
                print(f"{subject.name}: finished already, kept: {store.path}")
                continue
            head = header(subject)
            kept = store.begin(head)
            async with served(subject, server) as model:
                metrics = await evaluate(model, store, kept)
            store.finish(head, metrics)
        print(f"{subject.name}: {told(metrics)}; written to {store.path}")


def share(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"
