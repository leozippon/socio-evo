"""Capability: the resolved rate of an exported resident on held-out SWE-bench Verified tasks.

    python -m evaluation.capability AGENT_DIR --split eval --out OUT_DIR --model MODEL.yaml
        [--limit N] [--tasks ID ...] [--runtime RUNTIME.yaml] [--concurrency N]
        [--reasoning EFFORT]

Each task is worked by the resident's own runtime over a `world.solo.SoloPort`: the town's work
tools, through the same backend, with nothing of the town around them. For each task the agent
directory's background, memory and skills (never its session or trace) are copied into
OUT_DIR/<instance id>/agent, so the export is never written to and every task starts with a
fresh session; the trace written there is the record of the attempt, and every change handed in
is kept beside it as submission-N.patch. Skills are read-only in the harness, for every group:
the evaluation measures the resident as it stands, and within one task nothing written there
could be read back anyway. Tasks run concurrently, `concurrency` at a time.

A task's row says whether it was resolved, how it ended (`world.solo.Ending`), the submissions
and their verdicts, the model requests (steps) and their tokens, the real seconds and the
lapses. An infrastructure failure (a workspace or an acceptance that fails, a model that fails
every attempt at a reply, an error of the harness) makes the row an `error`, left out of the
resolved rate rather than counted against the resident. The resolved rate is resolved over
evaluated tasks, with a Wilson 95% interval. OUT_DIR must not exist; it receives the copies and
results.json: the configurations, the time taken, the summary and the rows.
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

from agent.directory import AREAS, BACKGROUND, AgentDirectory
from agent.runtime import Runtime, RuntimeConfig
from infrastructure.config import StrictModel, load_config
from infrastructure.llm import (
    LLMConfig,
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
    """The rows, and the resolved rate over the tasks evaluated (all but the errors) with its
    Wilson 95% interval; both None when every task was an error."""

    tasks: tuple[TaskResult, ...]
    evaluated: int
    resolved: int
    errors: int
    resolved_rate: float | None
    interval: tuple[float, float] | None

    @classmethod
    def of(cls, rows: Sequence[TaskResult]) -> CapabilityResult:
        evaluated = [row for row in rows if row.status != "error"]
        resolved = sum(row.resolved for row in evaluated)
        n = len(evaluated)
        return cls(
            tasks=tuple(rows),
            evaluated=n,
            resolved=resolved,
            errors=len(rows) - n,
            resolved_rate=resolved / n if n else None,
            interval=wilson(resolved, n) if n else None,
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
    the model `client`, `concurrency` tasks at a time; its copies and traces go under
    `out_dir`, which must not exist."""
    names = [task.instance_id for task in tasks]
    if not names:
        raise ValueError("no tasks to evaluate")
    if len(set(names)) < len(names):
        raise ValueError("a task is given more than once")
    AgentDirectory(export_dir)
    out_dir.mkdir(parents=True)
    gate = asyncio.Semaphore(concurrency)

    async def attempt(task: Task) -> TaskResult:
        async with gate:
            return await _attempt(
                task,
                export_dir,
                out_dir / task.instance_id,
                client,
                runtime_config,
                solo_config,
                backend,
            )

    return CapabilityResult.of(await asyncio.gather(*map(attempt, tasks)))


async def _attempt(
    task: Task,
    export_dir: Path,
    task_dir: Path,
    client: StreamingClient,
    runtime_config: RuntimeConfig,
    solo_config: SoloConfig,
    backend: Backend,
) -> TaskResult:
    """One task worked from a fresh copy of the resident; any exception is the row's error."""
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
            await port.close()
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
    never comes once the task is over; every reply is charged to the task's budget; a model
    that fails `attempts` times in a row, after which the runtime gives up the step as a lapse,
    ends the task as an error, and so does a reply without token usage. It serves `stream`
    alone, the one call the runtime makes."""

    def __init__(self, client: StreamingClient, port: SoloPort, attempts: int) -> None:
        self._client = client
        self._port = port
        self._attempts = attempts
        self._failures = 0

    async def stream(
        self, request: LLMRequest, *, abort: asyncio.Event | None = None
    ) -> LLMResponse:
        await self._port.turn()
        try:
            reply = await self._client.stream(request, abort=abort)
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
        self._port.spend(reply.usage.prompt_tokens + reply.usage.completion_tokens)
        return reply


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.capability", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("export", type=Path, help="exported agent directory")
    parser.add_argument("--split", required=True, choices=("train", "eval"))
    parser.add_argument("--limit", type=int, help="only the first N of the tasks chosen")
    parser.add_argument("--tasks", nargs="+", default=[], metavar="ID", help="only these tasks")
    parser.add_argument("--out", type=Path, required=True, help="directory to create")
    parser.add_argument("--model", type=Path, required=True, help="resident model LLMConfig YAML")
    parser.add_argument("--runtime", type=Path, help="RuntimeConfig YAML; defaults otherwise")
    parser.add_argument("--concurrency", type=int, default=4, help="tasks at a time")
    parser.add_argument("--reasoning", choices=("low", "medium", "xhigh"), help="over --runtime")
    args = parser.parse_args(argv)

    if args.out.exists():
        parser.error(f"would overwrite {args.out}")
    if args.concurrency < 1 or (args.limit is not None and args.limit < 1):
        parser.error("--concurrency and --limit must be at least 1")
    backend = SwebenchBackend()
    tasks = list(backend.load_split(args.split))
    if args.tasks:
        known = {task.instance_id: task for task in tasks}
        if unknown := [name for name in args.tasks if name not in known]:
            parser.error(f"not in the {args.split} split: {', '.join(unknown)}")
        tasks = [known[name] for name in dict.fromkeys(args.tasks)]
    tasks = tasks[: args.limit]
    backend.require_images(tasks)
    model = load_config(args.model, LLMConfig)
    runtime = load_config(args.runtime, RuntimeConfig) if args.runtime else RuntimeConfig()
    if args.reasoning:
        runtime = runtime.model_copy(update={"reasoning_effort": args.reasoning})
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
        "split": args.split,
        "model": model.model_dump(mode="json"),
        "runtime": runtime.model_dump(mode="json"),
        "solo": solo.model_dump(mode="json"),
        "concurrency": args.concurrency,
        "seconds": round(time.perf_counter() - started, 1),
        **result.model_dump(mode="json"),
    }
    results = args.out / "results.json"
    results.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
