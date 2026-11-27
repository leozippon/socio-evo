"""What the two evaluation commands (`evaluation.safety`, `evaluation.mask`) share: naming the
subjects on the command line, serving each in turn and skipping, resuming or beginning its
result.

    --run RUN --day N [--resident NAME ...] [--server YAML]   each resident's adapter at day N
    --run RUN --model NAME [--server YAML]                    the bare served model NAME

A resident's subject is the run's base model with the adapter `learning.adapters.adapter_for`
gives for its day, the base alone when no night has fitted it one. A day is refused until the
night after it is complete (its `done.json`), since until then the adapters of that day are not
final; a run that does not learn is scored on the base model, and the command says so. On day 0
every adapter is empty, so the subject of `--day 0` is the base model alone, as a bare model,
which stands for every resident. Before any run, RUN may be an experiment's configuration file,
which serves a bare model and day 0 and has no later day.
The adapter is loaded on every replica under a name of its own for the length of its evaluation
and unloaded after, so that it meets no other use of the same adapter. Everything is asked of
the run's server unless `--server` names another (an LLMConfig YAML): the reference model's, or,
for the residents, a server of the same base weights, onto which their adapters are loaded, so
that scoring never touches the server the town lives on. Such a server must serve the base under
the run's served name (its `model`), the one declaration of its weights there is; a result records
the server it was scored on in its provenance, and whether it was the run's.
A result is held by one process at a time; another that comes for it fails.
"""

import argparse
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from evaluation.results import MODELS, Store, model_result, resident_result, revision
from evaluation.subject import Run, Subject
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMConfig
from infrastructure.llm.adapters import load_adapter, unload_adapter
from infrastructure.storage import RunDirectory, day_tag
from learning.adapters import DONE, adapter_for

NAME = re.compile(r"[\w.-]+")
"""What a model's name must be to name its results' files."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="run directory (runs/RUN), or for a bare model or day 0 before any run an "
        "experiment's configuration file: its server and reasoning",
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
        help="LLMConfig YAML of the server to score on (default: the run's)",
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
    if args.server is not None and server.model != run.llm.model:
        parser.error(
            f"--server {args.server} serves {server.model}, not {run.llm.model}, the base of "
            f"{run.name}: its residents' adapters fit that base alone"
        )
    if args.day < 0:
        parser.error(f"day {args.day}: no such day")
    if args.day == 0:
        if args.resident:
            parser.error("on day 0 the base model stands for every resident: name none")
        return run, server, [Subject(base=run.llm.model)]
    if not run.begun:
        parser.error(f"--run {args.run} is a configuration, not a run: it has no day {args.day}")
    if unknown := [name for name in args.resident if name not in run.residents]:
        parser.error(f"{', '.join(unknown)}: no resident of {run.name}")
    names = args.resident or run.residents
    resident = {"base": run.llm.model, "run": run.name, "day": args.day}
    if not run.learns:
        print(f"{run.name} does not learn: its residents are scored on the base model")
        return run, server, [Subject(**resident, resident=name) for name in names]
    done = RunDirectory(run.path).night_dir(args.day) / DONE
    if not done.is_file():
        parser.error(
            f"day {args.day}: the night after it is not complete ({done} is missing), so the "
            "residents' adapters of the day are not final"
        )
    return run, server, [adapted(run, name, args.day, resident) for name in names]


def adapted(run: Run, name: str, day: int, resident: dict[str, Any]) -> Subject:
    """The subject of `name` after the complete night `day`: its adapter, and the night it was
    fitted on, by the run directory's layout of the adapters."""
    path = adapter_for(run.path, name, day)
    if path is None:
        return Subject(**resident, resident=name, night=day)
    directory = RunDirectory(run.path)
    fitted = [n for n in range(day, 0, -1) if directory.adapter_dir(name, n).resolve() == path]
    if not fitted:
        raise ValueError(f"{path}: the adapter of {name} is no night's of {run.name}")
    return Subject(**resident, resident=name, adapter=path, night=day, fitted=fitted[0])


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
    run: Run,
    subjects: list[Subject],
    server: LLMConfig,
    results: Path,
    benchmark: str,
    header: Callable[[Subject], dict[str, Any]],
    evaluate: Evaluate,
    told: Callable[[dict[str, Any]], str],
) -> None:
    """Each subject in turn, with the settings of `run`: a finished result told and kept, a
    running one resumed, and a new one begun; each serving of an adapter ends before the next
    begins. `told` says the metrics in a line."""
    provenance = {
        "run": run.name,
        "revision": revision(),
        "server": {"base_url": server.base_url, "the_runs": server.base_url == run.llm.base_url},
    }
    for subject in subjects:
        store = Store(result_of(results, benchmark, subject))
        with store.held():
            if store.finished:
                print(f"{subject.name}: finished already, kept: {store.path}")
                continue
            head = header(subject)
            kept = store.begin(head, provenance)
            async with served(subject, server) as model:
                metrics = await evaluate(model, store, kept)
            store.finish(head, metrics)
        print(f"{subject.name}: {told(metrics)}; written to {store.path}")


def share(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"
