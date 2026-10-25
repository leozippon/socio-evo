"""Pull the task images of the splits from ghcr.io and accept every task's gold patch in its image.

python -m tasks.swebench.pull [--split train|eval] [--workers N]

Images already on this machine are not pulled again, and a stopped pull resumes. A failure does
not stop the others: every image is tried and every pulled task's gold patch accepted, and the
failures are listed at the end, after which the command exits with an error. A task whose gold
patch is not resolved belongs in `UNRESOLVABLE`, after which `python -m tasks.swebench.dataset`
redraws the splits without it.
"""

import argparse
import asyncio
import time
from collections.abc import Sequence
from typing import get_args

from tasks.swebench.acceptance import accept
from tasks.swebench.dataset import Split, Task, load_split
from tasks.swebench.images import pull

GOLD_TIMEOUT_S = 1800


def main(argv: Sequence[str] | None = None) -> None:
    splits = get_args(Split)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=splits, help="only this split (default both)")
    parser.add_argument(
        "--workers", type=int, default=8, help="parallel pulls and acceptances (default 8)"
    )
    args = parser.parse_args(argv)
    chosen = [args.split] if args.split else splits
    tasks = [task for split in chosen for task in load_split(split)]
    failed = pull([task.image for task in tasks], workers=args.workers)
    pulled = [task for task in tasks if task.image not in failed]
    unresolved = asyncio.run(check_gold(pulled, args.workers))
    if failed or unresolved:
        lines = [f"  not pulled: {image}: {error}" for image, error in failed.items()]
        lines += [f"  gold not resolved: {instance}: {why}" for instance, why in unresolved.items()]
        raise SystemExit(f"{len(failed) + len(unresolved)} failures:\n" + "\n".join(lines))


async def check_gold(tasks: Sequence[Task], workers: int) -> dict[str, str]:
    """Accept the gold patch of every task, `workers` at a time, printing progress; returns why
    each task whose gold patch was not resolved was not."""
    gate = asyncio.Semaphore(max(1, workers))
    started = time.monotonic()

    async def one(task: Task) -> tuple[Task, str | None]:
        async with gate:
            try:
                verdict = await accept(task, task.patch, GOLD_TIMEOUT_S)
            except Exception as error:  # one task's failure must not stop the others
                return task, f"acceptance raised {type(error).__name__}: {error}"
        if verdict.resolved:
            return task, None
        (passed, total), (kept, before) = verdict.fail_to_pass, verdict.pass_to_pass
        return (
            task,
            f"{verdict.status}, {passed}/{total} FAIL_TO_PASS, {kept}/{before} PASS_TO_PASS",
        )

    print(f"accepting the gold patches of {len(tasks)} tasks")
    unresolved: dict[str, str] = {}
    for done, result in enumerate(asyncio.as_completed([one(task) for task in tasks]), 1):
        task, why = await result
        if why is not None:
            unresolved[task.instance_id] = why
        minutes = (time.monotonic() - started) / 60
        outcome = "resolved" if why is None else f"NOT RESOLVED ({why})"
        print(f"[{done}/{len(tasks)}, {minutes:.1f} min] {outcome} {task.instance_id}", flush=True)
    return dict(sorted(unresolved.items()))


if __name__ == "__main__":
    main()
