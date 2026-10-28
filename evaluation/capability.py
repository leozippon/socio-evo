"""Capability: the resolved rate of an exported resident on held-out SWE-bench Verified tasks.

    python -m evaluation.capability AGENT_DIR --split eval --out OUT_DIR [--limit N]
        [--tasks ID ...] [--concurrency N] [--compaction-threshold TOKENS]

AGENT_DIR is a resident of an export (`evaluation.exports`), and works with the model and the
runtime settings the export records, the run's own, except that `--compaction-threshold` may
replace the runtime's `compaction_threshold`, within the most the model's context window allows
(`RuntimeConfig.ceiling`). Each task is worked by the resident's own runtime over a
`world.solo.SoloPort`: the town's work tools, through the same backend, with nothing of the town
around them. For each task the agent directory's background, memory and skills (never its
session or trace) are copied into OUT_DIR/<instance id>/agent, so the export is never written to
and every task starts with a fresh session; the trace written there is the record of the
attempt, and every change handed in is kept beside it as submission-N.patch. Skills are
read-only in the harness: the evaluation measures the resident as it stands, and within one
task nothing written there could be read back anyway. Tasks run concurrently,
`concurrency` at a time.

A task's row says whether it was resolved, how it ended (`world.solo.Ending`), the submissions
and their verdicts, the model requests (steps) and their tokens, the real seconds and the
lapses. A task is bounded by requests and completion tokens, never by real time, whose yield
depends on the load of the model's server. An infrastructure failure (a workspace or an
acceptance that fails, a model that fails every attempt at a reply, a task run on to the safety
stop of real time, an error of the harness) makes the row an `error`, left out of the resolved
rate rather than counted against the resident. The resolved rate is resolved over evaluated
tasks, with a Wilson 95% interval.

OUT_DIR receives evaluation.json when it is created, saying what is evaluated (the export and
the resident's commit, the split, the model, the reasoning effort and the compaction threshold);
then each task's folder, with the task's row as result.json once the task is over; and, when
every task is over, results.json: the same, the configurations, the time taken, the summary
(with the count of rows of each ending), the rows and how many of them were resumed. Each file
is written whole or not at all. A stopped evaluation is continued by running the same command
again: the tasks whose row was written are kept, except error rows, and every other task folder,
an attempt cut off, is removed and its task worked again; the configurations and the time taken
in results.json are then those of the last invocation. An OUT_DIR that holds anything else, an
evaluation of something else (another export, commit or compaction threshold) or a finished one,
is refused.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import get_args

from agent.directory import AREAS, BACKGROUND, AgentDirectory
from agent.runtime import Runtime, RuntimeConfig
from evaluation.exports import Export
from infrastructure.config import StrictModel
from infrastructure.llm import (
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamingClient,
    create_client,
)
from infrastructure.storage import read_jsonl
from world.backend import Backend, SwebenchBackend, Task
from world.solo import Ending, SoloConfig, SoloPort

Z = 1.959964
"""The standard normal quantile of a two-sided 95% interval."""

RECORD = "evaluation.json"
RESULT = "result.json"
RESULTS = "results.json"
"""What OUT_DIR evaluates, a task's row in its folder, and the report (see the module docstring)."""


class TaskResult(StrictModel):
    """One task's row. `steps` are the model requests answered; `error` says what failed when
    `status` is `error`."""

    instance_id: str
    resolved: bool
    status: Ending
    submissions: int
    verdicts: tuple[str, ...]
    steps: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    seconds: float
    lapses: int
    error: str | None = None


class CapabilityResult(StrictModel):
    """The rows, how many ended each way, and the resolved rate over the tasks evaluated (all
    but the errors) with its Wilson 95% interval, both None when every task was an error;
    `resumed` rows were kept from an earlier invocation."""

    tasks: tuple[TaskResult, ...]
    evaluated: int
    resolved: int
    errors: int
    endings: dict[Ending, int]
    resolved_rate: float | None
    interval: tuple[float, float] | None
    resumed: int

    @classmethod
    def of(cls, rows: Sequence[TaskResult], resumed: int = 0) -> CapabilityResult:
        evaluated = [row for row in rows if row.status != "error"]
        resolved = sum(row.resolved for row in evaluated)
        n = len(evaluated)
        return cls(
            tasks=tuple(rows),
            evaluated=n,
            resolved=resolved,
            errors=len(rows) - n,
            endings={
                ending: sum(row.status == ending for row in rows) for ending in get_args(Ending)
            },
            resolved_rate=resolved / n if n else None,
            interval=wilson(resolved, n) if n else None,
            resumed=resumed,
        )


def wilson(successes: int, n: int) -> tuple[float, float]:
    """The Wilson score interval at 95% of a proportion of `successes` in `n` trials."""
    p = successes / n
    scale = 1 + Z**2 / n
    centre = (p + Z**2 / (2 * n)) / scale
    half = Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / scale
    return max(0.0, centre - half), min(1.0, centre + half)


async def evaluate_capability(
    export_dir: Path,
    tasks: Sequence[Task],
    client: StreamingClient,
    runtime_config: RuntimeConfig,
    solo_config: SoloConfig,
    *,
    concurrency: int,
    out_dir: Path,
    backend: Backend,
) -> CapabilityResult:
    """The resident exported at `export_dir` on each of `tasks`, worked through `backend` with
    the model `client`, `concurrency` tasks at a time; its copies, traces and rows go under
    `out_dir`, a task's row as its folder's result.json once the task is over. A task whose
    row is there already, written by an earlier invocation, is kept unless that row is an
    error, which is the machinery's and not the resident's; any other folder of a task is an
    attempt cut off, removed before the task is worked again."""
    names = [task.instance_id for task in tasks]
    if not names:
        raise ValueError("no tasks to evaluate")
    if len(set(names)) < len(names):
        raise ValueError("a task is given more than once")
    AgentDirectory(export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kept: dict[str, TaskResult] = {}
    for name in names:
        if (row := out_dir / name / RESULT).is_file():
            found = TaskResult.model_validate_json(row.read_text(encoding="utf-8"))
            if found.status != "error":
                kept[name] = found
                continue
        if (out_dir / name).exists():
            shutil.rmtree(out_dir / name)
    gate = asyncio.Semaphore(concurrency)

    async def attempt(task: Task) -> TaskResult:
        if task.instance_id in kept:
            return kept[task.instance_id]
        task_dir = out_dir / task.instance_id
        async with gate:
            row = await _attempt(
                task, export_dir, task_dir, client, runtime_config, solo_config, backend
            )
        _write(task_dir / RESULT, row.model_dump_json(indent=2) + "\n")
        return row

    rows = await asyncio.gather(*map(attempt, tasks))
    return CapabilityResult.of(rows, resumed=len(kept))


async def _attempt(
    task: Task,
    export_dir: Path,
    task_dir: Path,
    client: StreamingClient,
    runtime_config: RuntimeConfig,
    solo_config: SoloConfig,
    backend: Backend,
) -> TaskResult:
    """One task worked from a fresh copy of the resident; any exception is the row's error,
    except one in closing the workspace, which comes after the task has ended and so leaves its
    ending as it was: it is reported on stderr."""
    port: SoloPort | None = None
    failure: str | None = None
    seconds = 0.0
    try:
        directory = _copy(export_dir, task_dir / "agent")
        port = SoloPort(task, backend, solo_config, name=export_dir.name)
        metered = _Metered(client, port, runtime_config.model_attempts)
        try:
            await _live(Runtime(directory, port, metered, runtime_config), port)  # type: ignore[arg-type]
        finally:
            seconds = port.elapsed()
            try:
                await port.close()
            except Exception as error:
                print(
                    f"{task.instance_id}: the workspace was not closed: "
                    f"{type(error).__name__}: {error}",
                    file=sys.stderr,
                )
        for number, submission in enumerate(port.submissions, start=1):
            (task_dir / f"submission-{number}.patch").write_text(submission.patch, encoding="utf-8")
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    trace = task_dir / "agent" / "trace.jsonl"
    records = list(read_jsonl(trace)) if trace.exists() else []
    usage = [r["usage"] for r in records if r["kind"] == "reply" and r["usage"]]
    submissions = port.submissions if port is not None else []
    status: Ending = "error"
    if failure is None and port is not None and port.ending is not None:
        status = port.ending
    return TaskResult(
        instance_id=task.instance_id,
        resolved=status == "accepted",
        status=status,
        submissions=len(submissions),
        verdicts=tuple(submission.verdict.status for submission in submissions),
        steps=sum(r["kind"] == "reply" for r in records),
        prompt_tokens=sum(u["prompt_tokens"] for u in usage),
        completion_tokens=sum(u["completion_tokens"] for u in usage),
        cached_tokens=sum(u["cached_prompt_tokens"] or 0 for u in usage),
        seconds=round(seconds, 1),
        lapses=sum(r["kind"] == "lapse" for r in records),
        error=failure or (port.error if port is not None else None),
    )


def _copy(export: Path, destination: Path) -> AgentDirectory:
    """The resident's own files of `export` (background, memory, skills) copied to
    `destination`, which must not exist: an agent directory with no session or trace yet, its
    skills read-only."""
    destination.mkdir(parents=True)
    shutil.copy2(export / BACKGROUND, destination / BACKGROUND)
    for area in AREAS:
        if (export / area).is_dir():
            shutil.copytree(export / area, destination / area)
    return AgentDirectory(destination, skills_writable=False)


def _claim(out_dir: Path, record: dict[str, str | int], names: Sequence[str]) -> None:
    """Take `out_dir` for the evaluation `record` of the tasks `names`: create it with the
    record, or continue it when an earlier invocation of the same evaluation left it
    unfinished. Raise ValueError when it holds anything else or a finished evaluation."""
    if (results := out_dir / RESULTS).is_file():
        report = json.loads(results.read_text(encoding="utf-8"))
        done = {row["instance_id"] for row in report["tasks"]}
        if missing := [name for name in names if name not in done]:
            raise ValueError(
                f"would overwrite {out_dir}: its evaluation is finished, without {len(missing)} "
                "of the tasks chosen; a finished evaluation is not extended"
            )
        raise ValueError(f"would overwrite {out_dir}: its evaluation is finished")
    if not out_dir.exists():
        out_dir.mkdir(parents=True)
        _write(out_dir / RECORD, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return
    if not (out_dir / RECORD).is_file():
        raise ValueError(
            f"would overwrite {out_dir}: it holds no {RECORD} to say what it evaluates"
        )
    begun = json.loads((out_dir / RECORD).read_text(encoding="utf-8"))
    if changed := [key for key, value in record.items() if begun.get(key) != value]:
        raise ValueError(
            f"would overwrite {out_dir}: it was begun with "
            + "; ".join(f"{key} {begun.get(key)}, not {record[key]}" for key in changed)
        )


def _write(path: Path, text: str) -> None:
    """`text` as the content of `path`, written whole or not at all: to a temporary file beside
    it, then renamed."""
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


async def _live(runtime: Runtime, port: SoloPort) -> None:
    """Run `runtime` until its task is over, then cancel it; an error that stopped it first is
    raised."""
    run = asyncio.create_task(runtime.run())
    over = asyncio.create_task(port.done.wait())
    try:
        await asyncio.wait((run, over), return_when=asyncio.FIRST_COMPLETED)
    finally:
        run.cancel()
        over.cancel()
        await asyncio.gather(run, over, return_exceptions=True)
    if not port.done.is_set():
        raise run.exception() or RuntimeError("the runtime stopped before the task was over")


class _Metered:
    """`client` as the resident on `port` meets it. A request waits for the port's leave, which
    never comes once the task is over; every reply's completion tokens are charged to the
    task's budget, its prompt tokens only reported in the row; a model that fails `attempts`
    times in a row, after which the runtime gives up the step as a lapse, ends the task as an
    error, and so does a reply without token usage. It serves `stream` alone, the one call the
    runtime makes."""

    def __init__(self, client: StreamingClient, port: SoloPort, attempts: int) -> None:
        self._client = client
        self._port = port
        self._attempts = attempts
        self._failures = 0

    async def stream(self, request: LLMRequest) -> LLMResponse:
        await self._port.turn()
        try:
            reply = await self._client.stream(request)
        except LLMError as error:
            self._failures += 1
            if self._failures >= self._attempts:
                self._port.end(
                    "error",
                    f"the model failed {self._failures} times in a row: "
                    f"{type(error).__name__}: {error}",
                )
            raise
        self._failures = 0
        if reply.usage is None:
            self._port.end("error", "the model reported no token usage")
            await self._port.turn()
            raise AssertionError("unreachable: the task is over")
        self._port.spend(reply.usage.completion_tokens)
        return reply


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.capability", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("export", type=Path, help="exported agent directory")
    parser.add_argument("--split", required=True, choices=("train", "eval"))
    parser.add_argument("--limit", type=int, help="only the first N of the tasks chosen")
    parser.add_argument("--tasks", nargs="+", default=[], metavar="ID", help="only these tasks")
    parser.add_argument(
        "--out", type=Path, required=True, help="directory to create, or to continue"
    )
    parser.add_argument("--concurrency", type=int, default=4, help="tasks at a time")
    parser.add_argument(
        "--compaction-threshold",
        type=int,
        metavar="TOKENS",
        help="compact the resident's context past this many tokens (default: the export's)",
    )
    args = parser.parse_args(argv)

    counts = (args.concurrency, args.limit, args.compaction_threshold)
    if any(count is not None and count < 1 for count in counts):
        parser.error("--concurrency, --limit and --compaction-threshold must be at least 1")
    try:
        export = Export.of(args.export)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    model, runtime = export.llm, export.runtime
    if args.compaction_threshold is not None:
        runtime = runtime.model_copy(update={"compaction_threshold": args.compaction_threshold})
        window = model.context_window
        if window is not None and args.compaction_threshold > runtime.ceiling(window):
            parser.error(
                f"--compaction-threshold {args.compaction_threshold} is above "
                f"{runtime.ceiling(window)}, the most the model's context window of {window} "
                "tokens allows"
            )
    backend = SwebenchBackend()
    tasks = list(backend.load_split(args.split))
    if args.tasks:
        known = {task.instance_id: task for task in tasks}
        if unknown := [name for name in args.tasks if name not in known]:
            parser.error(f"not in the {args.split} split: {', '.join(unknown)}")
        tasks = [known[name] for name in dict.fromkeys(args.tasks)]
    tasks = tasks[: args.limit]
    record = {
        "export": str(args.export.resolve()),
        "commit": export.commit(args.export),
        "split": args.split,
        "model": model.model,
        "reasoning_effort": runtime.reasoning_effort,
        "compaction_threshold": runtime.compaction_threshold,
    }
    try:
        _claim(args.out, record, [task.instance_id for task in tasks])
    except ValueError as error:
        parser.error(str(error))
    backend.require_images(tasks)
    solo = SoloConfig()

    started = time.perf_counter()
    result = asyncio.run(
        evaluate_capability(
            args.export,
            tasks,
            create_client(model),
            runtime,
            solo,
            concurrency=args.concurrency,
            out_dir=args.out,
            backend=backend,
        )
    )
    report = {
        "export": str(args.export.resolve()),
        "commit": export.commit(args.export),
        "split": args.split,
        "model": model.model_dump(mode="json"),
        "runtime": runtime.model_dump(mode="json"),
        "solo": solo.model_dump(mode="json"),
        "concurrency": args.concurrency,
        "seconds": round(time.perf_counter() - started, 1),
        **result.model_dump(mode="json"),
    }
    results = args.out / RESULTS
    _write(results, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    rate = (
        "no task evaluated"
        if result.resolved_rate is None or result.interval is None
        else f"resolved rate {result.resolved_rate:.3f} "
        f"(95% CI {result.interval[0]:.3f}-{result.interval[1]:.3f})"
    )
    print(
        f"{result.resolved} of {result.evaluated} tasks resolved, {rate}, "
        f"{result.errors} errors; written to {results}"
    )
    if result.errors:
        sys.exit(f"{result.errors} tasks failed outside the resident; see their rows")


if __name__ == "__main__":
    main()
